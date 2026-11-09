"""HTTP API used by the mobile app. Bearer-token protected; /api/health is open."""

from __future__ import annotations

import hmac
import logging
import re

from aiohttp import web

from .cloudfs import FILE_RE, MIME, CloudError, clip_kind, ext_of
from .notify import valid_token
from .ptz import DIRECTIONS, SPEEDS, PtzError

log = logging.getLogger("sentinel.api")

S_KEY = web.AppKey("S", object)
TOKEN_KEY = web.AppKey("token", str)

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}


@web.middleware
async def middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=CORS)
    if request.path != "/api/health":
        sent = request.headers.get("Authorization", "")
        expected = "Bearer " + request.app[TOKEN_KEY]
        if not hmac.compare_digest(sent.encode(), expected.encode()):
            return web.json_response({"error": "unauthorized"}, status=401, headers=CORS)
    try:
        resp = await handler(request)
    except web.HTTPException as exc:
        resp = web.json_response({"error": exc.reason}, status=exc.status)
    resp.headers.update(CORS)
    return resp


async def _body(request: web.Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_app(S) -> web.Application:
    app = web.Application(middlewares=[middleware])
    app[S_KEY] = S
    app[TOKEN_KEY] = S.cfg["api"]["token"]
    r = web.RouteTableDef()

    @r.get("/api/health")
    async def health(request):
        return web.json_response({"ok": True})

    @r.get("/api/status")
    async def status(request):
        return web.json_response(S.status())

    @r.post("/api/arm")
    async def arm(request):
        body = await _body(request)
        res = S.cmd_arm(force=bool(body.get("force")))
        return web.json_response(res, status=200 if res["ok"] else 409)

    @r.post("/api/disarm")
    async def disarm(request):
        return web.json_response(S.cmd_disarm())

    @r.post("/api/siren/test")
    async def siren_test(request):
        res = await S.cmd_siren_test()
        return web.json_response(res, status=200 if res["ok"] else 409)

    @r.post("/api/siren/silence")
    async def siren_silence(request):
        res = S.cmd_silence_siren()
        return web.json_response(res, status=200 if res["ok"] else 409)

    @r.get("/api/settings")
    async def get_settings(request):
        return web.json_response({"settings": S.settings, "effective": S.effective(), "timezone": str(S.tz)})

    @r.post("/api/settings")
    async def set_settings(request):
        try:
            new = S.update_settings(await _body(request))
        except ValueError as exc:
            return web.json_response({"error": "invalid", "detail": str(exc)}, status=400)
        return web.json_response({"settings": new, "effective": S.effective(), "timezone": str(S.tz)})

    @r.post("/api/sensors/{name}")
    async def sensor(request):
        body = await _body(request)
        if not isinstance(body.get("enabled"), bool):
            return web.json_response({"error": "invalid", "detail": "enabled must be true or false"}, status=400)
        res = S.cmd_sensor(
            request.match_info["name"], body["enabled"],
            minutes=body.get("minutes"), until_closed=bool(body.get("until_closed")),
        )
        return web.json_response(res, status=200 if res["ok"] else 400 if res["error"] != "unknown_sensor" else 404)

    @r.post("/api/schedule/skip")
    async def schedule_skip(request):
        body = await _body(request)
        res = S.cmd_schedule_skip(str(body.get("date", "today")), bool(body.get("skip", True)))
        return web.json_response(res, status=200 if res["ok"] else 400)

    @r.post("/api/schedule/pause")
    async def schedule_pause(request):
        body = await _body(request)
        res = S.cmd_schedule_pause(body.get("minutes", 0))
        return web.json_response(res, status=200 if res["ok"] else 400)

    @r.post("/api/schedule/resume")
    async def schedule_resume(request):
        return web.json_response(S.cmd_schedule_resume())

    @r.get("/api/insights")
    async def insights(request):
        try:
            days = int(request.query.get("days", "14"))
        except ValueError:
            days = 14
        return web.json_response(S.insights(days))

    @r.get("/api/events")
    async def events(request):
        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            limit = 50
        return web.json_response({"events": S.store.recent(limit)})

    @r.get("/api/snapshot")
    async def snapshot(request):
        jpeg = await S.snapshot()
        if jpeg is None:
            return web.json_response({"error": "camera_unavailable"}, status=503)
        return web.Response(body=jpeg, content_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @r.get("/api/live")
    async def live(request):
        return web.json_response({"hls": S.cfg["live"]["hls_url"].format(host=request.url.host)})

    # ---- recordings of an incident (cloud folder, or the Pi while they are still waiting to upload)
    @r.get("/api/events/{event_id}/clips")
    async def event_clips(request):
        info = await S.clips(request.match_info["event_id"])
        if info is None:
            raise web.HTTPNotFound(reason="unknown_event")
        return web.json_response(info)

    def _parse_range(header: str | None, size: int):
        """One 'bytes=a-b' range -> (start, end) inclusive; None = whole file; False = not satisfiable."""
        if not header:
            return None
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
        if not m or (m.group(1) == "" and m.group(2) == ""):
            return None
        if m.group(1) == "":                                  # the last N bytes
            n = int(m.group(2))
            return (max(0, size - n), size - 1) if n else False
        start = int(m.group(1))
        end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        return (start, end) if start < size and start <= end else False

    @r.get("/api/events/{event_id}/clips/{name}")
    async def event_clip(request):
        event_id, name = request.match_info["event_id"], request.match_info["name"]
        folder = S.event_folder(event_id)
        if folder is None or not FILE_RE.match(name) or not clip_kind(name):
            raise web.HTTPNotFound(reason="unknown_clip")
        mime = MIME[ext_of(name)]
        local = S.spool / folder / name
        if local.is_file():                                   # not uploaded yet: serve from the Pi (supports ranges)
            return web.FileResponse(local, headers={"Content-Type": mime, **CORS})
        try:
            entry = next((f for f in await S.cloud.files(folder) if f["name"] == name), None)
        except CloudError as exc:
            if exc.detail == "not_found":                     # the folder is gone (clean-up) or never existed
                raise web.HTTPNotFound(reason="unknown_clip")
            return web.json_response({"error": exc.detail}, status=502)
        if entry is None:
            raise web.HTTPNotFound(reason="unknown_clip")
        size = entry["size"]
        rng = _parse_range(request.headers.get("Range"), size)
        if rng is False:
            return web.Response(status=416, headers={"Content-Range": f"bytes */{size}", **CORS})
        start, end = rng if rng else (0, size - 1)
        headers = {"Content-Type": mime, "Accept-Ranges": "bytes", "Content-Length": str(end - start + 1),
                   "Cache-Control": "private, max-age=3600", **CORS}
        if rng:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        resp = web.StreamResponse(status=206 if rng else 200, headers=headers)
        await resp.prepare(request)
        try:
            async for chunk in S.cloud.stream(folder, name, start, end - start + 1):
                await resp.write(chunk)
            await resp.write_eof()
        except (ConnectionResetError, CloudError):
            pass                                              # the phone left, or the cloud stopped answering
        return resp

    @r.post("/api/cloud/cleanup")
    async def cloud_cleanup(request):
        return web.json_response({"ok": True, "result": await S.cleanup(manual=True), "retention": S.retention()})

    @r.post("/api/vacation")
    async def vacation(request):
        body = await _body(request)
        res = S.cmd_vacation(body.get("active"), body.get("days"))
        return web.json_response(res, status=200 if res["ok"] else 400)

    # ---- pan / tilt (Reolink)
    def _ptz():
        if S.ptz is None:
            raise web.HTTPNotFound(reason="ptz_unavailable")
        return S.ptz

    def _ptz_fail(exc: Exception):
        if isinstance(exc, web.HTTPException):          # e.g. 404 ptz_unavailable: let the middleware answer
            raise exc
        if not isinstance(exc, PtzError):
            log.exception("camera control failed", exc_info=exc)
            return web.json_response({"error": "camera_error"}, status=502)
        status = 400 if exc.detail in ("bad_direction", "bad_preset", "bad_name", "no_free_slot") else 502
        return web.json_response({"error": exc.detail}, status=status)

    @r.get("/api/ptz")
    async def ptz_info(request):
        if S.ptz is None:
            return web.json_response({"supported": False, "presets": [], "speeds": list(SPEEDS)})
        try:
            presets = await S.ptz.presets()
        except PtzError as exc:
            if exc.detail in ("camera_unreachable", "camera_login_failed"):
                return _ptz_fail(exc)
            presets = []                           # a camera without presets still moves
        except Exception as exc:
            return _ptz_fail(exc)
        return web.json_response({
            "supported": True, "presets": presets, "speed": S.ptz.speed_name,
            "speeds": list(SPEEDS), "arm_preset": S.arm_preset, "directions": list(DIRECTIONS),
        })

    @r.post("/api/ptz/move")
    async def ptz_move(request):
        body = await _body(request)
        speed = body.get("speed")
        if speed is not None and speed not in SPEEDS:
            return web.json_response({"error": "bad_speed"}, status=400)
        try:
            seconds = float(body.get("seconds", 0.5))
        except (TypeError, ValueError):
            return web.json_response({"error": "bad_seconds"}, status=400)
        try:
            await _ptz().move(str(body.get("direction", "")), seconds, speed)
        except Exception as exc:
            return _ptz_fail(exc)
        return web.json_response({"ok": True})

    @r.post("/api/ptz/stop")
    async def ptz_stop(request):
        try:
            await _ptz().stop()
        except Exception as exc:
            return _ptz_fail(exc)
        return web.json_response({"ok": True})

    @r.post("/api/ptz/preset/go")
    async def ptz_go(request):
        try:
            await _ptz().goto((await _body(request)).get("id"))
        except Exception as exc:
            return _ptz_fail(exc)
        return web.json_response({"ok": True})

    @r.post("/api/ptz/preset/save")
    async def ptz_save(request):
        body = await _body(request)
        try:
            saved = await _ptz().save(str(body.get("name", "")), body.get("id"))
        except Exception as exc:
            return _ptz_fail(exc)
        return web.json_response({"ok": True, **saved})

    @r.post("/api/ptz/preset/delete")
    async def ptz_delete(request):
        try:
            await _ptz().delete((await _body(request)).get("id"))
        except Exception as exc:
            return _ptz_fail(exc)
        return web.json_response({"ok": True})

    @r.post("/api/register")
    async def register(request):
        token = (await _body(request)).get("token", "")
        if not valid_token(token):
            return web.json_response({"error": "invalid_token"}, status=400)
        S.store.add_token(token)
        return web.json_response({"ok": True})

    @r.post("/api/unregister")
    async def unregister(request):
        token = (await _body(request)).get("token", "")
        S.store.remove_token(token)
        return web.json_response({"ok": True})

    @r.post("/api/test-push")
    async def test_push(request):
        devices = len(S.store.tokens())
        n = await S.notifier.send("info", "Test notification", "Push alerts from the Pi are working.")
        out = {"ok": n > 0, "delivered": n, "devices": devices}
        if n == 0:
            out["error"] = S.notifier.last_error or "not_delivered"
        return web.json_response(out)

    app.add_routes(r)
    return app
