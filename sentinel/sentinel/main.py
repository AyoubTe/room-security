"""Wires everything together and runs the service."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import signal
import time
from datetime import datetime
from pathlib import Path

import aiohttp

from . import __version__, insights, schedule, settings as cfgmod
from .api import build_app
from .camera import grab_jpeg, rtsp_input
from .config import load, timezone
from .engine import ACTIVE_STATES, DISARMED, Engine, SensorCfg, Timing
from .mqttio import Z2M, siren_payloads
from .notify import Notifier
from .cloudfs import CloudError, CloudFs, FILE_RE, clip_kind, folder_time
from .ptz import PtzError, ReolinkPtz, ptz_settings
from .recorder import Recorder, folder_name
from .store import Store
from .system import snapshot as system_snapshot
from .uploader import Uploader

log = logging.getLogger("sentinel")

ARMED_OR_BEFORE = ("exit_delay", "armed", "entry_delay")   # states the schedule may disarm (never an active alarm)


def _dur(seconds: float) -> str:
    m = int(round(seconds / 60))
    if m < 60:
        return f"{m} min"
    h, r = divmod(m, 60)
    return f"{h} h" if not r else f"{h} h {r} min"


class Sentinel:
    def __init__(self, cfg: dict, loop: asyncio.AbstractEventLoop, clock=time.time, mqtt=True):
        self.cfg = cfg
        self.loop = loop
        self.clock = clock
        self.started = clock()
        data = Path(cfg["paths"]["data_dir"])
        data.mkdir(parents=True, exist_ok=True)
        self.store = Store(data / "sentinel.db")
        self.notifier = Notifier(self.store, enabled=cfg["push"]["enabled"])

        sensors = [
            SensorCfg(
                name=s["name"], z2m=s["z2m"], kind=s["kind"],
                label=s.get("label", ""), entry_delay=bool(s.get("entry_delay", False)),
            )
            for s in cfg["sensors"]
        ]
        timing_keys = Timing.__dataclass_fields__.keys()
        timing = Timing(**{k: v for k, v in cfg["timing"].items() if k in timing_keys})
        timing.siren_s = float(cfg["siren"]["duration_s"]) if "siren_s" not in cfg["timing"] else timing.siren_s
        self.engine = Engine(sensors, timing, clock())
        self.tz = timezone(cfg)
        self.sensor_names = [s.name for s in sensors]
        self._base_delays = (timing.exit_delay_s, timing.entry_delay_s, timing.siren_s)
        self.settings = cfgmod.load(self.store.get("settings"), self.sensor_names, self.tz, clock())
        self._apply_settings(clock(), first=True)
        self.sched: dict = {"enabled": False, "state": "off", "vacation": {"active": False, "since": None, "until": None}}
        self._warned_for: float | None = None
        self._postponed_for: float | None = None

        self.uploader = Uploader(
            cfg, Path(cfg["paths"]["data_dir"]) / "spool",
            on_failing=lambda err: self._push_task("warn", "Cloud upload failing", f"Clips are kept on the Pi. {err or ''}"[:200]),
            on_recovered=lambda: self._push_task("info", "Cloud upload recovered", "Queued clips are uploading again."),
        )
        self.recorder = Recorder(cfg, self.uploader, clock)
        ptz_cfg = ptz_settings(cfg["camera"])
        self.ptz: ReolinkPtz | None = ReolinkPtz(ptz_cfg) if ptz_cfg else None
        self.arm_preset = ptz_cfg["arm_preset"] if ptz_cfg else 0
        self.cloud = CloudFs(cfg, clock)
        self._aimed: tuple[str, float] | None = None
        self.z2m = Z2M(cfg, loop, self.on_values, self.on_avail, self.on_bridge) if mqtt else None

        self.queue: asyncio.Queue = asyncio.Queue()           # recorder work (slow), in order
        self.siren_queue: asyncio.Queue = asyncio.Queue()     # siren commands, strictly in order
        self._tasks: list[asyncio.Task] = []
        self._bg: set[asyncio.Task] = set()
        self._last_armed: tuple | None = None

    # ------------------------------------------------------------ plumbing
    def _push_task(self, level: str, title: str, body: str) -> None:
        t = self.loop.create_task(self.notifier.send(level, title, body))
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    def flush(self) -> None:
        # Logs, push notifications and the siren are never made to wait behind slow
        # recorder work (e.g. stopping ffmpeg): they run immediately / on their own queue.
        for fx in self.engine.drain():
            kind = fx[0]
            if kind == "log":
                self.store.add_log(fx[1], fx[2], fx[3], data=fx[4] if len(fx) > 4 else None, ts=self.clock())
            elif kind == "notify":
                self._push_task(fx[1], fx[2], fx[3])
            elif kind == "siren":
                self.siren_queue.put_nowait(fx[1])
            elif kind == "aim":
                self._aim_camera(fx[1])
            else:
                self.queue.put_nowait(fx)
        armed = "1" if self.engine.export_state()["armed"] else "0"
        key = (armed, self.engine.armed_by)
        if key != self._last_armed:
            if armed == "1" and self._last_armed is not None and self._last_armed[0] == "0":
                self._park_camera()
            self._last_armed = key
            self.store.set("armed", armed)
            self.store.set("armed_by", self.engine.armed_by)

    def _park_camera(self) -> None:
        """Turn the camera back to the saved watch position when the room is armed (camera.ptz.arm_preset)."""
        if not (self.ptz and self.arm_preset):
            return

        async def go():
            try:
                await self.ptz.goto(self.arm_preset)
            except PtzError as exc:
                log.warning("could not park the camera on preset %s: %s", self.arm_preset, exc.detail)

        t = self.loop.create_task(go())
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    def _aim_camera(self, sensor: str) -> None:
        """Turn the camera to the saved view picked for this sensor (settings.camera.views)."""
        cam = self.settings["camera"]
        view = cam["views"].get(sensor)
        if not (self.ptz and cam["follow"] and view is not None):
            return
        now = self.clock()
        if self._aimed and self._aimed[0] == sensor and now - self._aimed[1] < 20:
            return                                    # already looking there
        self._aimed = (sensor, now)

        async def go():
            try:
                await self.ptz.goto(view)
                self.store.add_log("camera", f"Camera turned to saved view {view} ({sensor})", None, ts=self.clock())
            except PtzError as exc:
                log.warning("could not turn the camera to view %s: %s", view, exc.detail)

        t = self.loop.create_task(go())
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    async def _apply(self, fx: tuple) -> None:
        kind = fx[0]
        if kind == "camera":
            await (self.recorder.camera_on() if fx[1] else self.recorder.camera_off())
        elif kind == "rec_start":
            self.recorder.event_start(fx[1], fx[2])
        elif kind == "rec_alarm":
            await self.recorder.event_alarm()
        elif kind == "rec_stop":
            info = await self.recorder.event_stop(stop_camera=fx[3])
            if info:
                parts = info.get("parts", 0)
                if self.uploader.configured:
                    text = f"{parts} clip(s) saved to cloud folder {info['folder']}"
                else:
                    text = f"{parts} clip(s) kept on the Pi ({info['folder']}); cloud not configured"
                self.store.add_log("clips", text, fx[1], data=info, ts=self.clock())
        elif kind == "rec_cancel":
            await self.recorder.event_cancel(stop_camera=fx[2])

    async def _worker(self) -> None:
        while True:
            fx = await self.queue.get()
            try:
                await self._apply(fx)
            except Exception:
                log.exception("effect failed: %s", fx)

    async def _siren_worker(self) -> None:
        while True:
            on = await self.siren_queue.get()
            try:
                await self._siren(on)
            except Exception:
                log.exception("siren command failed")

    async def _siren(self, on: bool, duration: float | None = None) -> bool:
        s = self.cfg["siren"]
        if not s["enabled"] or self.z2m is None:
            return False
        ok = True
        vol = self.settings["siren"]["volume"]
        for payload in siren_payloads(s, on, duration, volume=vol):
            ok = self.z2m.publish(s["z2m"], payload) and ok
            await asyncio.sleep(0.3)
        return ok

    # ------------------------------------------------------------ inputs
    def on_values(self, name: str, values: dict) -> None:
        now = self.clock()
        self._sync(now)
        self.engine.sensor_message(name, values, now)
        self.flush()

    def on_avail(self, name: str, online: bool) -> None:
        self.engine.availability(name, online, self.clock())
        self.flush()

    def on_bridge(self, online: bool) -> None:
        self.engine.bridge(online, self.clock())
        self.flush()

    # ------------------------------------------------------------ commands (API)
    def cmd_arm(self, force: bool = False) -> dict:
        now = self.clock()
        self._sync(now)
        res = self.engine.arm(now, force)
        if res["ok"]:
            self.store.set("sched_suspended", "")      # you armed it yourself: schedule steps aside
        self.flush()
        return res

    def cmd_disarm(self) -> dict:
        now = self.clock()
        was_armed = self.engine.state != DISARMED
        res = self.engine.disarm(now)
        if was_armed and self.vacation_on(now):
            self.store.set("sched_suspended", "vacation")
            self.engine.fx.append(("log", "schedule", "Vacation arming paused (you disarmed manually). Press Resume to arm again", None))
            res["schedule_suspended"] = True
        elif was_armed and self.settings["schedule"]["enabled"]:
            ev = schedule.evaluate(self.settings["schedule"], now, self.tz)
            if ev["active"]:
                # You disarmed inside a scheduled window (you came into the room): don't re-arm
                # until the window is over, or until you press Resume.
                self.store.set("sched_suspended", f"{ev['window_start']:.0f}")
                self.engine.fx.append(("log", "schedule", "Auto-arm paused until this window ends (you disarmed manually)", None))
                res["schedule_suspended"] = True
        self.flush()
        return res

    def cmd_silence_siren(self) -> dict:
        res = self.engine.silence_siren(self.clock())
        self.flush()
        return res

    # ---- sensors (zone bypass)
    def cmd_sensor(self, name: str, enabled: bool, minutes: int | None = None, until_closed: bool = False) -> dict:
        if name not in self.engine.sensors:
            return {"ok": False, "error": "unknown_sensor"}
        if minutes is not None and (isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 1 <= minutes <= 1440):
            return {"ok": False, "error": "bad_minutes"}
        now = self.clock()
        z = self.settings["sensors"][name]
        label = self.engine.sensors[name].cfg.title()
        if enabled:
            z.update(enabled=True, until=None, until_closed=False, saw_open=False)
            text = f"{label} sensor turned back on"
        else:
            z.update(
                enabled=False,
                until=now + minutes * 60 if minutes else None,
                until_closed=bool(until_closed),
                saw_open=self.engine.sensors[name].state == "open",
            )
            how = []
            if until_closed:
                how.append("until it is closed again")
            if minutes:
                how.append(f"for at most {_dur(minutes * 60)}")
            text = f"{label} sensor turned off" + (" " + ", ".join(how) if how else " until you turn it back on")
        self._save_settings()
        self.engine.set_bypass(name, not enabled)
        self.engine.fx.append(("log", "zone_on" if enabled else "zone_off", text, None))
        self.flush()
        return {"ok": True, "sensor": self._sensor_settings(name)}

    def _sensor_settings(self, name: str) -> dict:
        z = self.settings["sensors"][name]
        return {"name": name, "enabled": z["enabled"], "until": z["until"], "until_closed": z["until_closed"]}

    # ---- settings
    def update_settings(self, patch: dict, quiet: bool = False) -> dict:
        now = self.clock()
        new = cfgmod.apply_patch(self.settings, patch, self.sensor_names, self.tz, now)
        changed = [k for k in patch if new.get(k) != self.settings.get(k)]
        self.settings = new
        self._save_settings()
        self._apply_settings(now)
        if changed and not quiet:
            self.engine.fx.append(("log", "settings", "Settings changed: " + ", ".join(changed), None))
        self.flush()
        return self.settings

    def _save_settings(self) -> None:
        self.store.set("settings", json.dumps(self.settings))

    def _apply_settings(self, now: float, first: bool = False) -> None:
        exit_s, entry_s, siren_s = self._base_delays
        t = self.settings["timing"]
        self.engine.t.exit_delay_s = t["exit_delay_s"] or exit_s
        self.engine.t.entry_delay_s = t["entry_delay_s"] or entry_s
        self.engine.t.siren_s = self.settings["siren"]["duration_s"] or siren_s
        for name, z in self.settings["sensors"].items():
            self.engine.set_bypass(name, not z["enabled"])
        self._sync(now)

    def insights(self, days: int = 14) -> dict:
        days = max(1, min(int(days), 60))
        now = self.clock()
        since = now - (days + 1) * 86400
        return insights.build(
            self.store.since(since), now, self.tz, days,
            armed_now=self.engine.state in ACTIVE_STATES,
        )

    def effective(self) -> dict:
        t = self.engine.t
        return {"exit_delay_s": t.exit_delay_s, "entry_delay_s": t.entry_delay_s, "siren_duration_s": t.siren_s}

    def _sync(self, now: float) -> None:
        self.engine.silent = cfgmod.siren_silent(self.settings, now, self.tz)

    # ---- schedule actions
    def cmd_schedule_skip(self, day: str, skip: bool) -> dict:
        now = self.clock()
        if day == "today":
            day = datetime.fromtimestamp(now, self.tz).date().isoformat()
        elif day == "tomorrow":
            from datetime import timedelta
            day = (datetime.fromtimestamp(now, self.tz).date() + timedelta(days=1)).isoformat()
        dates = set(self.settings["schedule"]["skip_dates"])
        dates.add(day) if skip else dates.discard(day)
        try:
            self.update_settings({"schedule": {"skip_dates": sorted(dates)}}, quiet=True)
        except ValueError as exc:
            return {"ok": False, "error": "invalid", "detail": str(exc)}
        self.engine.fx.append(("log", "schedule", f"{day} marked as {'a day at home (schedule skipped)' if skip else 'a normal day'}", None))
        self.flush()
        return {"ok": True, "date": day, "skipped": skip}

    def cmd_schedule_pause(self, minutes: int) -> dict:
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 0 <= minutes <= 10080:
            return {"ok": False, "error": "bad_minutes"}
        now = self.clock()
        until = now + minutes * 60 if minutes else None
        self.update_settings({"schedule": {"paused_until": until}}, quiet=True)
        text = f"Schedule paused for {_dur(minutes * 60)}" if minutes else "Schedule pause cleared"
        self.engine.fx.append(("log", "schedule", text, None))
        self.flush()
        return {"ok": True, "paused_until": until}

    def cmd_schedule_resume(self) -> dict:
        self.store.set("sched_suspended", "")
        self.update_settings({"schedule": {"paused_until": None}}, quiet=True)
        self.engine.fx.append(("log", "schedule", "Schedule resumed", None))
        self.flush()
        return {"ok": True}

    async def cmd_siren_test(self) -> dict:
        if self.engine.state != "disarmed":
            return {"ok": False, "error": "not_disarmed"}
        ok = await self._siren(True, self.cfg["siren"]["test_s"])
        return {"ok": ok, "error": None if ok else "siren_unavailable"}

    # ---- recordings in the cloud: list, clean up
    EVENT_RE = re.compile(r"^\d{9,11}-[0-9a-f]{4}$")

    @property
    def spool(self) -> Path:
        return Path(self.cfg["paths"]["data_dir"]) / "spool"

    def event_folder(self, event_id: str) -> str | None:
        if not self.EVENT_RE.match(str(event_id)):
            return None
        # The folder name is derived from the event id; the log entry is only a cross-check for old events.
        return self.store.clip_folder(event_id) or folder_name(float(event_id.split("-")[0]), event_id)

    async def clips(self, event_id: str) -> dict | None:
        folder = self.event_folder(event_id)
        if folder is None:
            return None
        items: dict[str, dict] = {}
        local = self.spool / folder
        if local.is_dir():                                    # still waiting to be uploaded: playable from the Pi
            for p in sorted(local.iterdir()):
                kind = clip_kind(p.name)
                if p.is_file() and p.suffix != ".tmp" and kind and FILE_RE.match(p.name):
                    items[p.name] = {"name": p.name, "size": p.stat().st_size, "kind": kind, "where": "pi"}
        error = None
        if self.cloud.configured:
            try:
                for f in await self.cloud.files(folder):
                    items.setdefault(f["name"], {**f, "where": "cloud"})
            except CloudError as exc:
                if exc.detail != "not_found":                 # a folder that was cleaned up is simply gone
                    error = exc.detail
        rec = self.recorder.event
        return {
            "event_id": event_id, "folder": folder, "error": error,
            "recording": bool(rec and rec.id == event_id),
            "clips": sorted(items.values(), key=lambda c: c["name"]),
        }

    def retention(self) -> dict:
        try:
            last = json.loads(self.store.get("cleanup_last") or "null")
            usage = json.loads(self.store.get("cloud_usage") or "null")
        except ValueError:
            last = usage = None
        return {
            "days": self.settings["cloud"]["retention_days"],
            "hold": self.vacation_on(),                       # nothing is deleted while you are away
            "at": self.cfg["cloud"]["cleanup_at"],
            "last": last,
            "usage": usage,
        }

    async def refresh_usage(self) -> None:
        if not self.cloud.configured:
            return
        try:
            self.store.set("cloud_usage", json.dumps(await self.cloud.size()))
        except CloudError as exc:
            log.warning("could not measure the cloud folder: %s", exc.detail)

    async def cleanup(self, manual: bool = False) -> dict:
        """Delete alerts and recordings older than the retention period (never while on vacation)."""
        now = self.clock()
        days = self.settings["cloud"]["retention_days"]
        res = {"at": now, "manual": manual, "folders": 0, "rows": 0, "skipped": None, "error": None}
        if days == 0:
            res["skipped"] = "keep_forever"
        elif self.vacation_on(now) and not manual:
            res["skipped"] = "vacation"
        else:
            cutoff = now - days * 86400
            res["rows"] = self.store.purge_before(cutoff)
            if self.cloud.configured:
                try:
                    for name in await self.cloud.folders():
                        t = folder_time(name, self.tz)
                        if t is not None and t < cutoff:
                            await self.cloud.purge(name)
                            res["folders"] += 1
                except CloudError as exc:
                    res["error"] = exc.detail
            if res["folders"] or res["rows"] or res["error"]:
                what = f"{res['folders']} recording(s) and {res['rows']} old alert(s) older than {days} days deleted"
                self.store.add_log("cleanup", what if not res["error"] else f"Clean-up incomplete ({res['error']}): {what}", None, ts=self.clock())
        self.store.set("cleanup_last", json.dumps(res))
        await self.refresh_usage()
        log.info("clean-up: %s", res)
        return res

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                now = self.clock()
                local = datetime.fromtimestamp(now, self.tz)
                due_min = schedule.minutes_of(self.cfg["cloud"]["cleanup_at"])
                today = local.date().isoformat()
                if local.hour * 60 + local.minute >= due_min and self.store.get("cleanup_day") != today:
                    self.store.set("cleanup_day", today)
                    await self.cleanup()
                else:
                    usage = json.loads(self.store.get("cloud_usage") or "null")
                    if self.cloud.configured and (not usage or now - usage.get("at", 0) > 6 * 3600):
                        await self.refresh_usage()
            except Exception:
                log.exception("clean-up loop failed")
            await asyncio.sleep(300)

    async def snapshot(self) -> bytes | None:
        cam = self.cfg["camera"]
        url = cam.get("rtsp_sub") or cam.get("rtsp_main")
        if cam.get("input_args"):
            args = cam["input_args"]
        elif url:
            args = rtsp_input(url)
        else:
            return None
        return await grab_jpeg(cam["ffmpeg"], args)

    def status(self) -> dict:
        now = self.clock()
        out = self.engine.snapshot(now)
        out.update({
            "version": __version__,
            "uptime_s": int(now - self.started),
            "mqtt_ok": bool(self.z2m and self.z2m.connected),
            "cloud": self.uploader.status(),
            "retention": self.retention(),
            "recording": self.recorder.status(),
            "siren_enabled": bool(self.cfg["siren"]["enabled"]),
            "siren_mode": self.settings["siren"]["mode"],
            "timezone": str(self.tz),
            "schedule": self.sched,
            "system": system_snapshot(self.cfg["paths"]["data_dir"]),
            "server_time": now,
        })
        for sensor in out["sensors"]:
            z = self.settings["sensors"][sensor["name"]]
            sensor.update(enabled=z["enabled"], bypass_until=z["until"], bypass_until_closed=z["until_closed"])
        return out

    # ------------------------------------------------------------ loops
    def _maintain_bypass(self, now: float) -> None:
        """Ends timed / until-closed sensor bypasses and warns if the sensor is still open."""
        dirty = False
        for name, z in self.settings["sensors"].items():
            if z["enabled"]:
                continue
            sensor = self.engine.sensors[name]
            expired = False
            if z["until"] and now >= z["until"]:
                expired = True
            elif z["until_closed"]:
                if sensor.state == "open" and not z["saw_open"]:
                    z["saw_open"] = dirty = True
                elif sensor.state == "closed" and z["saw_open"]:
                    expired = True
            if not expired:
                continue
            z.update(enabled=True, until=None, until_closed=False, saw_open=False)
            dirty = True
            self.engine.set_bypass(name, False)
            label = sensor.cfg.title()
            self.engine.fx.append(("log", "zone_on", f"{label} sensor is active again", None))
            if self.engine.state in ACTIVE_STATES:
                if sensor.cfg.kind == "contact" and sensor.state == "open":
                    self.engine._notify("warn", f"{label} still open",
                                        f"{label} is protected again but it is still open, so it cannot detect anything until it is closed.")
                else:
                    self.engine._notify("info", f"{label} sensor active", f"{label} is being watched again.")
        if dirty:
            self._save_settings()

    def vacation_on(self, now: float | None = None) -> bool:
        v = self.settings["schedule"]["vacation"]
        return bool(v["active"] and (not v["until"] or (now or self.clock()) < v["until"]))

    def _end_vacation(self, now: float, expired: bool) -> None:
        e = self.engine
        self.update_settings({"schedule": {"vacation": {"active": False, "since": None, "until": None}}}, quiet=True)
        if self.store.get("sched_suspended") == "vacation":
            self.store.set("sched_suspended", "")
        text = "Vacation mode ended. Welcome back." if expired else "Vacation mode turned off. Welcome back."
        if e.armed_by == "schedule" and e.state != DISARMED:
            e.disarm(now, by="schedule")
            text += " The room is disarmed."
        e.fx.append(("log", "vacation", text, None))
        e._notify("info", "Vacation mode ended", text)

    def cmd_vacation(self, active, days=None) -> dict:
        if not isinstance(active, bool):
            return {"ok": False, "error": "bad_request"}
        if days is not None and (isinstance(days, bool) or not isinstance(days, (int, float)) or not 1 <= days <= 365):
            return {"ok": False, "error": "bad_days"}
        now = self.clock()
        if active:
            until = now + days * 86400 if days else None
            self.update_settings({"schedule": {"vacation": {"active": True, "since": now, "until": until}}}, quiet=True)
            self.store.set("sched_suspended", "")
            when = ("until " + datetime.fromtimestamp(until, self.tz).strftime("%a %d %b")) if until else "until you turn it off"
            text = f"Vacation mode on, armed day and night {when}"
            self.engine.fx.append(("log", "vacation", text, None))
            self.engine._notify("info", "Vacation mode on", f"The room stays armed day and night {when}. Old recordings are kept meanwhile.")
        elif self.vacation_on(now):
            self._end_vacation(now, expired=False)
        self._schedule_tick(now)                          # so the answer (and /api/status) reflects it at once
        self.flush()
        return {"ok": True, "vacation": self.settings["schedule"]["vacation"]}

    def _schedule_tick(self, now: float) -> None:
        if self.settings["schedule"]["vacation"]["active"] and not self.vacation_on(now):
            self._end_vacation(now, expired=True)         # the planned end date has passed
        sc = self.settings["schedule"]
        vac = self.vacation_on(now)
        e = self.engine
        ev = schedule.evaluate(sc, now, self.tz)
        if sc["paused_until"] and now >= sc["paused_until"]:
            sc["paused_until"] = None
            self._save_settings()
        paused = bool(sc["paused_until"])
        suspended = ev["window_start"] is not None and self.store.get("sched_suspended") == f"{ev['window_start']:.0f}"
        if vac:
            suspended = self.store.get("sched_suspended") == "vacation"
        state, reason = "off", None

        if vac:
            # Away: armed round the clock. Windows, days at home and pauses do not apply.
            if suspended:
                state, reason = "suspended", "You disarmed manually. Press Resume to let vacation mode arm again."
            elif e.state != DISARMED:
                state = "vacation"
            else:
                blockers = e.open_sensors()
                busy = e.room_busy(now, sc["busy_s"]) if sc["smart_arm"] else []
                if blockers or busy:
                    state = "postponed"
                    reason = (f"{', '.join(blockers)} open" if blockers else f"Movement seen by {', '.join(busy)}")
                    if self._postponed_for != "vacation":
                        self._postponed_for = "vacation"
                        e._notify("warn", "Vacation arming postponed", f"{reason}. It will arm as soon as the room is clear.")
                        e._log("schedule", f"Vacation arming postponed: {reason}")
                else:
                    self._postponed_for = None
                    e.arm(now, by="schedule")
                    state = "vacation"
        elif sc["enabled"]:
            if paused:
                state = "paused"
            elif ev["active"]:
                if suspended:
                    state, reason = "suspended", "You disarmed manually. Press Resume to let the schedule arm again."
                elif e.state != DISARMED:
                    state = "armed"
                else:
                    blockers = e.open_sensors()
                    busy = e.room_busy(now, sc["busy_s"]) if sc["smart_arm"] else []
                    if blockers or busy:
                        state = "postponed"
                        reason = (f"{', '.join(blockers)} open" if blockers else f"Movement seen by {', '.join(busy)}")
                        if self._postponed_for != ev["window_start"]:
                            self._postponed_for = ev["window_start"]
                            e._notify("warn", "Auto-arm postponed", f"{reason}. It will arm as soon as the room is clear.")
                            e._log("schedule", f"Auto-arm postponed: {reason}")
                    else:
                        e.arm(now, by="schedule")
                        state = "armed"
            else:
                state = "skipped" if ev["skipped_now"] else "idle"
                if sc["auto_disarm"] and e.armed_by == "schedule" and e.state in (ARMED_OR_BEFORE):
                    e.disarm(now, by="schedule")
                    e._notify("info", "Disarmed", "Schedule window ended.")
                # heads-up before the next automatic arming
                warn = sc["pre_arm_warning_min"] * 60
                nxt = ev["next_start"]
                if (warn and nxt and e.state == DISARMED and 0 < nxt - now <= warn and self._warned_for != nxt):
                    self._warned_for = nxt
                    at = datetime.fromtimestamp(nxt, self.tz).strftime("%H:%M")
                    e._notify("info", f"Auto-arm at {at}",
                              f"The room will be armed in {max(1, round((nxt - now) / 60))} min. Open the app to skip today if you are staying.")

        self.sched = {
            "enabled": sc["enabled"],
            "state": state,
            "reason": reason,
            "active": ev["active"],
            "window_start": ev["window_start"],
            "window_end": ev["window_end"],
            "next_start": ev["next_start"],
            "next_end": ev["next_end"],
            "skipped_now": ev["skipped_now"],
            "skipped_next": ev["skipped_next"],
            "paused_until": sc["paused_until"],
            "suspended": suspended,
            "vacation": {"active": vac, "since": sc["vacation"]["since"], "until": sc["vacation"]["until"]},
        }

    def tick_once(self) -> None:
        now = self.clock()
        self._sync(now)
        self._maintain_bypass(now)
        self._schedule_tick(now)
        self.engine.tick(now)
        self.flush()

    async def _tick_loop(self) -> None:
        while True:
            try:
                self.tick_once()
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(1)

    async def _recorder_loop(self) -> None:
        while True:
            try:
                await self.recorder.tick()
                self.engine.camera(self.recorder.camera_ok, self.clock())
                self.flush()
            except Exception:
                log.exception("recorder tick failed")
            await asyncio.sleep(3)

    async def _health_loop(self) -> None:
        url = self.cfg.get("healthchecks_url")
        if not url:
            return
        while True:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
                    await http.get(url)
            except Exception as exc:
                log.debug("healthcheck ping failed: %s", exc)
            await asyncio.sleep(60)

    async def start(self) -> None:
        self.engine.restore(self.store.get("armed") == "1", self.clock(), self.store.get("armed_by") or "user")
        self.flush()
        if self.z2m:
            self.z2m.start()
        for coro in (self._worker(), self._siren_worker(), self._tick_loop(), self._recorder_loop(),
                     self._health_loop(), self.uploader.run(), self._cleanup_loop()):
            self._tasks.append(self.loop.create_task(coro))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self.uploader.stop()
        if self.z2m:
            self.z2m.stop()
        await self.recorder.shutdown()
        if self.ptz:
            await self.ptz.close()


async def amain(config_path: str) -> None:
    cfg = load(config_path)
    loop = asyncio.get_running_loop()
    app_obj = Sentinel(cfg, loop)
    await app_obj.start()

    from aiohttp import web

    runner = web.AppRunner(build_app(app_obj))
    await runner.setup()
    site = web.TCPSite(runner, cfg["api"]["host"], int(cfg["api"]["port"]))
    await site.start()
    log.info("sentinel %s listening on %s:%s", __version__, cfg["api"]["host"], cfg["api"]["port"])

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    log.info("shutting down")
    await runner.cleanup()
    await app_obj.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="sentinel")
    parser.add_argument("--config", default="/etc/sentinel/config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(amain(args.config))
