"""Pan/tilt control for a Reolink camera, through the camera's own HTTP API (port 80).

Nothing to configure in the usual case: the camera address, user and password are taken from
`camera.rtsp_main` / `camera.rtsp_sub`. Override under `camera.ptz` when needed.

Safety: a movement is always bounded. Every move carries a duration (default 0.5 s, at most 3 s)
after which the Pi sends Stop by itself, so a dropped phone connection never leaves the camera
turning until it hits its end stop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import unquote, urlparse

import aiohttp

log = logging.getLogger("sentinel.ptz")

# Direction name used by the app -> Reolink PtzCtrl "op"
DIRECTIONS = {
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "up_left": "LeftUp", "up_right": "RightUp", "down_left": "LeftDown", "down_right": "RightDown",
}
MAX_MOVE_S = 3.0
DEFAULT_MOVE_S = 0.5
SPEEDS = {"slow": 12, "normal": 28, "fast": 48}     # Reolink accepts 1..64
NO_LOGIN = {-6, -7}                                  # rspCode: login first / token expired
MAX_PRESET_ID = 64


class PtzError(Exception):
    """The camera refused or could not be reached. `detail` is safe to show in the app."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def ptz_settings(cam_cfg: dict) -> dict | None:
    """Work out host/port/user/password. Returns None when PTZ is switched off or cannot be derived."""
    p = dict(cam_cfg.get("ptz") or {})
    if p.get("enabled") is False:
        return None
    user, password, host = p.get("user"), p.get("password"), p.get("host")
    if not (user and password and host):
        for key in ("rtsp_main", "rtsp_sub"):
            raw = cam_cfg.get(key) or ""
            if not raw:
                continue
            u = urlparse(raw)
            if u.hostname:
                host = host or u.hostname
                user = user or (unquote(u.username) if u.username else None)
                password = password or (unquote(u.password) if u.password else None)
                break
    if not (host and user and password):
        return None
    return {
        "host": host, "port": int(p.get("port", 80)), "user": user, "password": password,
        "channel": int(p.get("channel", 0)), "speed": p.get("speed", "normal"),
        "arm_preset": int(p.get("arm_preset", 0) or 0),
    }


class ReolinkPtz:
    def __init__(self, settings: dict, clock=time.monotonic):
        self.s = settings
        self.clock = clock
        scheme = "https" if self.s["port"] == 443 else "http"
        self.base = f"{scheme}://{self.s['host']}:{self.s['port']}/cgi-bin/api.cgi"
        self._http: aiohttp.ClientSession | None = None
        self._token: str | None = None
        self._token_until = 0.0
        self._lock = asyncio.Lock()               # one command at a time: ordering matters for move/stop
        self._stop_task: asyncio.Task | None = None
        self.cmds = 0                              # counts moves and go-to commands: lets callers tell whether someone else moved the camera
        self.speed_name = self.s["speed"] if self.s["speed"] in SPEEDS else "normal"

    # ------------------------------------------------------------ transport
    def _session(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=6),
                connector=aiohttp.TCPConnector(ssl=False),
            )
        return self._http

    async def _post(self, query: str, body: list) -> dict:
        try:
            async with self._session().post(f"{self.base}?{query}", json=body) as r:
                data = await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            log.warning("camera request failed: %s: %s", type(exc).__name__, exc)
            raise PtzError("camera_unreachable") from exc
        except ValueError as exc:                 # the camera answered, but not with JSON (a web page, an empty body)
            log.warning("camera sent a reply that is not JSON: %s", exc)
            raise PtzError("bad_reply") from exc
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            log.warning("unexpected camera reply: %.200r", data)
            raise PtzError("bad_reply")
        return data[0]

    async def _login(self) -> None:
        body = [{"cmd": "Login", "param": {"User": {
            "Version": "0", "userName": self.s["user"], "password": self.s["password"]}}}]
        res = await self._post("cmd=Login", body)
        token = (res.get("value") or {}).get("Token") or {}
        if res.get("code") != 0 or not token.get("name"):
            raise PtzError("camera_login_failed")
        self._token = token["name"]
        self._token_until = self.clock() + max(60, int(token.get("leaseTime", 3600)) - 60)

    async def _call(self, cmd: str, action: int, param: dict) -> dict:
        """Send one command, logging in first (and once more if the token was refused)."""
        for attempt in (0, 1):
            if not self._token or self.clock() >= self._token_until:
                await self._login()
            res = await self._post(f"cmd={cmd}&token={self._token}", [{"cmd": cmd, "action": action, "param": param}])
            err = res.get("error") or {}
            if res.get("code") == 0:
                return res
            if err.get("rspCode") in NO_LOGIN and attempt == 0:
                self._token = None
                continue
            raise PtzError("camera_refused")
        raise PtzError("camera_refused")

    # ------------------------------------------------------------ public
    def speed_value(self, name: str | None = None) -> int:
        return SPEEDS.get(name or self.speed_name, SPEEDS["normal"])

    async def move(self, direction: str, seconds: float = DEFAULT_MOVE_S, speed: str | None = None) -> None:
        op = DIRECTIONS.get(direction)
        if op is None:
            raise PtzError("bad_direction")
        seconds = min(max(float(seconds), 0.1), MAX_MOVE_S)
        self.cmds += 1
        async with self._lock:
            self._cancel_stop()
            await self._call("PtzCtrl", 0, {"channel": self.s["channel"], "op": op, "speed": self.speed_value(speed)})
            self._stop_task = asyncio.get_running_loop().create_task(self._stop_later(seconds))

    async def stop(self) -> None:
        async with self._lock:
            self._cancel_stop()
            await self._call("PtzCtrl", 0, {"channel": self.s["channel"], "op": "Stop"})

    async def _table(self) -> list[dict]:
        """The camera's preset slots. Firmware differs: a list of slots, or {"table": [...]} inside a dict."""
        res = await self._call("GetPtzPreset", 1, {"channel": self.s["channel"]})
        raw = (res.get("value") or {}).get("PtzPreset")
        if isinstance(raw, dict):
            raw = raw.get("table")
        return [p for p in (raw or []) if isinstance(p, dict) and isinstance(p.get("id"), int)]

    async def presets(self) -> list[dict]:
        return [
            {"id": p["id"], "name": str(p.get("name") or f"Position {p['id']}")}
            for p in await self._table() if p.get("enable")
        ]

    async def goto(self, preset_id: int) -> None:
        self._check_id(preset_id)
        self.cmds += 1
        async with self._lock:
            self._cancel_stop()
            await self._call("PtzCtrl", 0, {
                "channel": self.s["channel"], "op": "ToPos", "id": int(preset_id), "speed": self.speed_value()})

    async def save(self, name: str, preset_id: int | None = None) -> dict:
        """Remember the camera's current direction. Picks the first free slot unless one is given."""
        name = (name or "").strip()[:31]
        if not name:
            raise PtzError("bad_name")
        table = await self._table()
        if preset_id is None:
            # Prefer a slot the camera itself lists as empty; otherwise the first unused number.
            used = {p["id"] for p in table if p.get("enable")}
            empty = [p["id"] for p in table if not p.get("enable")]
            preset_id = min(empty) if empty else next((i for i in range(1, MAX_PRESET_ID + 1) if i not in used), None)
            if preset_id is None:
                raise PtzError("no_free_slot")
        self._check_id(preset_id)
        async with self._lock:
            await self._call("SetPtzPreset", 0, {"PtzPreset": {
                "channel": self.s["channel"], "enable": 1, "id": int(preset_id), "name": name}})
        return {"id": int(preset_id), "name": name}

    async def delete(self, preset_id: int) -> None:
        self._check_id(preset_id)
        async with self._lock:
            await self._call("SetPtzPreset", 0, {"PtzPreset": {
                "channel": self.s["channel"], "enable": 0, "id": int(preset_id), "name": ""}})

    async def close(self) -> None:
        self._cancel_stop()
        if self._http and not self._http.closed:
            await self._http.close()

    # ------------------------------------------------------------ internals
    @staticmethod
    def _check_id(preset_id) -> None:
        if isinstance(preset_id, bool) or not isinstance(preset_id, int) or not 0 <= preset_id <= MAX_PRESET_ID:
            raise PtzError("bad_preset")

    def _cancel_stop(self) -> None:
        if self._stop_task and not self._stop_task.done():
            self._stop_task.cancel()
        self._stop_task = None

    async def _stop_later(self, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
            async with self._lock:
                await self._call("PtzCtrl", 0, {"channel": self.s["channel"], "op": "Stop"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:                  # never let a failed auto-stop crash the loop
            log.warning("auto-stop failed: %s", exc)
