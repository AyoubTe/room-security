"""Pan/tilt: a fake Reolink HTTP API stands in for the camera."""

import asyncio
import copy

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from sentinel.api import build_app
from sentinel.config import DEFAULTS, validate
from sentinel.main import Sentinel
from sentinel.ptz import PtzError, ReolinkPtz, ptz_settings

from test_service import AUTH, FakeZ2M, make_cfg


class FakeCamera:
    """Implements the few Reolink commands the Pi uses."""

    def __init__(self, password="test-camera-pass", list_format=False):
        self.password = password
        self.list_format = list_format      # some firmware answers {"PtzPreset": [...]} instead of {"PtzPreset": {"table": [...]}}
        self.log = []                       # ("Left", speed) / ("Stop",) / ("ToPos", id)
        self.logins = 0
        self.expire_token = False           # next command answers "please login first"
        self.presets = {1: "Door"}
        self.token = None

    async def handle(self, request):
        body = (await request.json())[0]
        cmd, param = body["cmd"], body.get("param", {})
        if cmd == "Login":
            u = param["User"]
            if u["password"] != self.password:
                return self._reply(cmd, 1, error={"rspCode": -27, "detail": "login failed"})
            self.logins += 1
            self.token = f"tok{self.logins}"
            return self._reply(cmd, 0, value={"Token": {"name": self.token, "leaseTime": 3600}})
        if request.query.get("token") != self.token or self.expire_token:
            self.expire_token = False
            return self._reply(cmd, 1, error={"rspCode": -6, "detail": "please login first"})
        if cmd == "PtzCtrl":
            if param["op"] == "Stop":
                self.log.append(("Stop",))
            elif param["op"] == "ToPos":
                self.log.append(("ToPos", param["id"]))
            else:
                self.log.append((param["op"], param["speed"]))
            return self._reply(cmd, 0, value={"rspCode": 200})
        if cmd == "GetPtzPreset":
            table = [{"id": i, "name": n, "enable": 1} for i, n in self.presets.items()]
            table.append({"id": 9, "name": "", "enable": 0})
            if self.list_format:
                return self._reply(cmd, 0, value={"PtzPreset": table})
            return self._reply(cmd, 0, value={"PtzPreset": {"channel": 0, "table": table}})
        if cmd == "SetPtzPreset":
            p = param["PtzPreset"]
            if p["enable"]:
                self.presets[p["id"]] = p["name"]
            else:
                self.presets.pop(p["id"], None)
            return self._reply(cmd, 0, value={"rspCode": 200})
        return self._reply(cmd, 1, error={"rspCode": -9})

    @staticmethod
    def _reply(cmd, code, value=None, error=None):
        out = {"cmd": cmd, "code": code}
        out.update({"value": value} if value is not None else {"error": error})
        return web.json_response([out])


async def camera_server(cam):
    app = web.Application()
    app.router.add_post("/cgi-bin/api.cgi", cam.handle)
    server = TestServer(app)
    await server.start_server()
    return server


def settings_for(server, password="test-camera-pass"):
    return {"host": "127.0.0.1", "port": server.port, "user": "admin", "password": password,
            "channel": 0, "speed": "normal", "arm_preset": 0}


def test_settings_come_from_the_rtsp_url():
    cam = {"rtsp_main": "rtsp://admin:My%40Pass@192.168.1.60:554/Preview_01_main", "ptz": {"enabled": True}}
    s = ptz_settings(cam)
    assert s["host"] == "192.168.1.60" and s["user"] == "admin" and s["password"] == "My@Pass" and s["port"] == 80
    assert ptz_settings({"rtsp_main": "", "ptz": {}}) is None                     # nothing to derive from
    assert ptz_settings({**cam, "ptz": {"enabled": False}}) is None               # switched off
    over = ptz_settings({**cam, "ptz": {"host": "10.0.0.5", "port": 8080}})
    assert over["host"] == "10.0.0.5" and over["port"] == 8080


def test_config_validation_of_ptz():
    cfg = copy.deepcopy(DEFAULTS)
    cfg["api"]["token"] = "x"
    cfg["sensors"] = [{"name": "a", "z2m": "a", "kind": "contact"}]
    validate(cfg)
    cfg["camera"]["ptz"]["speed"] = "warp"
    try:
        validate(cfg)
        raise AssertionError("bad speed accepted")
    except ValueError:
        pass
    cfg["camera"]["ptz"].update({"speed": "fast", "arm_preset": 99})
    try:
        validate(cfg)
        raise AssertionError("bad preset accepted")
    except ValueError:
        pass


def test_move_stops_by_itself_and_login_is_reused():
    async def run():
        cam = FakeCamera()
        server = await camera_server(cam)
        ptz = ReolinkPtz(settings_for(server))
        try:
            await ptz.move("left", 0.2)
            await ptz.move("up", 0.2, "fast")
            assert cam.log[0] == ("Left", 28) and cam.log[1] == ("Up", 48)
            await asyncio.sleep(0.5)
            assert cam.log[-1] == ("Stop",)                 # the Pi stopped the camera by itself
            assert cam.log.count(("Stop",)) == 1            # the first auto-stop was cancelled by the second move
            assert cam.logins == 1                          # one login, token reused
            await ptz.move("right", 0.3)
            await ptz.stop()                                # an explicit stop cancels the pending auto-stop
            await asyncio.sleep(0.5)
            assert cam.log[-2:] == [("Right", 28), ("Stop",)] and cam.log.count(("Stop",)) == 2
            try:
                await ptz.move("sideways")
                raise AssertionError("bad direction accepted")
            except PtzError as exc:
                assert exc.detail == "bad_direction"
        finally:
            await ptz.close()
            await server.close()

    asyncio.run(run())


def test_expired_token_is_refreshed_and_wrong_password_reported():
    async def run():
        cam = FakeCamera()
        server = await camera_server(cam)
        ptz = ReolinkPtz(settings_for(server))
        bad = ReolinkPtz(settings_for(server, password="wrong"))
        try:
            await ptz.stop()
            cam.expire_token = True
            await ptz.stop()                                # camera forgot us: log in again and retry
            assert cam.logins == 2 and cam.log == [("Stop",), ("Stop",)]
            try:
                await bad.stop()
                raise AssertionError("wrong password accepted")
            except PtzError as exc:
                assert exc.detail == "camera_login_failed"
        finally:
            await ptz.close()
            await bad.close()
            await server.close()

    asyncio.run(run())


def test_presets_in_the_list_format_used_by_some_firmware():
    async def run():
        cam = FakeCamera(list_format=True)
        server = await camera_server(cam)
        ptz = ReolinkPtz(settings_for(server))
        try:
            assert await ptz.presets() == [{"id": 1, "name": "Door"}]
            assert await ptz.save("Bed") == {"id": 9, "name": "Bed"}        # uses the slot the camera lists as empty
            assert [p["id"] for p in await ptz.presets()] == [1, 9]
        finally:
            await ptz.close()
            await server.close()

    asyncio.run(run())


def test_camera_answering_with_a_web_page_gives_a_clean_error():
    async def run():
        async def page(request):
            return web.Response(text="<html>Not the API</html>", content_type="text/html")

        app = web.Application()
        app.router.add_post("/cgi-bin/api.cgi", page)
        server = TestServer(app)
        await server.start_server()
        ptz = ReolinkPtz(settings_for(server))
        try:
            await ptz.stop()
            raise AssertionError("a web page was accepted as a camera reply")
        except PtzError as exc:
            assert exc.detail == "bad_reply"
        finally:
            await ptz.close()
            await server.close()

    asyncio.run(run())


def test_presets_save_go_delete():
    async def run():
        cam = FakeCamera()
        server = await camera_server(cam)
        ptz = ReolinkPtz(settings_for(server))
        try:
            assert await ptz.presets() == [{"id": 1, "name": "Door"}]       # disabled slots are not listed
            saved = await ptz.save("Bed")
            assert saved == {"id": 9, "name": "Bed"}                         # the slot the camera lists as empty
            await ptz.goto(9)
            assert cam.log[-1] == ("ToPos", 9)
            await ptz.delete(9)
            assert [p["id"] for p in await ptz.presets()] == [1]
            for bad in (-1, 65, "1", True):
                try:
                    await ptz.goto(bad)
                    raise AssertionError(f"{bad!r} accepted")
                except PtzError as exc:
                    assert exc.detail == "bad_preset"
        finally:
            await ptz.close()
            await server.close()

    asyncio.run(run())


def test_api_endpoints_and_unavailable_camera(tmp_path):
    async def run():
        cam = FakeCamera()
        server = await camera_server(cam)
        cfg = make_cfg(tmp_path)
        cfg["camera"]["rtsp_sub"] = f"rtsp://admin:test-camera-pass@127.0.0.1:554/Preview_01_sub"
        cfg["camera"]["ptz"]["port"] = server.port
        S = Sentinel(cfg, asyncio.get_running_loop(), mqtt=False)
        S.z2m = FakeZ2M()
        client = TestClient(TestServer(build_app(S)))
        await client.start_server()
        try:
            assert (await client.get("/api/ptz")).status == 401
            info = await (await client.get("/api/ptz", headers=AUTH)).json()
            assert info["supported"] and info["presets"] == [{"id": 1, "name": "Door"}]

            r = await client.post("/api/ptz/move", json={"direction": "left", "seconds": 0.2}, headers=AUTH)
            assert r.status == 200 and cam.log[-1] == ("Left", 28)
            r = await client.post("/api/ptz/move", json={"direction": "diagonal"}, headers=AUTH)
            assert r.status == 400
            r = await client.post("/api/ptz/move", json={"direction": "up", "speed": "warp"}, headers=AUTH)
            assert r.status == 400
            assert (await client.post("/api/ptz/stop", headers=AUTH)).status == 200

            r = await client.post("/api/ptz/preset/save", json={"name": "Desk"}, headers=AUTH)
            assert r.status == 200
            new_id = (await r.json())["id"]
            assert (await client.post("/api/ptz/preset/save", json={"name": " "}, headers=AUTH)).status == 400
            assert (await client.post("/api/ptz/preset/go", json={"id": new_id}, headers=AUTH)).status == 200
            assert (await client.post("/api/ptz/preset/go", json={"id": "x"}, headers=AUTH)).status == 400
            assert (await client.post("/api/ptz/preset/delete", json={"id": new_id}, headers=AUTH)).status == 200

            cam.password = "changed"                              # camera rejects us from now on
            S.ptz._token = None
            r = await client.post("/api/ptz/stop", headers=AUTH)
            assert r.status == 502 and (await r.json())["error"] == "camera_login_failed"

            S.ptz = None                                          # no camera address known
            info = await (await client.get("/api/ptz", headers=AUTH)).json()
            assert info["supported"] is False
            assert (await client.post("/api/ptz/stop", headers=AUTH)).status == 404
        finally:
            await client.close()
            await server.close()
            S.store.db.close()

    asyncio.run(run())


def test_camera_parks_on_the_watch_position_when_armed(tmp_path):
    async def run():
        cam = FakeCamera()
        server = await camera_server(cam)
        cfg = make_cfg(tmp_path)
        cfg["camera"]["rtsp_sub"] = "rtsp://admin:test-camera-pass@127.0.0.1:554/Preview_01_sub"
        cfg["camera"]["ptz"].update({"port": server.port, "arm_preset": 1})
        S = Sentinel(cfg, asyncio.get_running_loop(), mqtt=False)
        S.z2m = FakeZ2M()
        try:
            S.flush()                                             # first flush records "disarmed"
            S.cmd_arm(force=True)
            await asyncio.sleep(0.5)
            assert cam.log == [("ToPos", 1)]
            S.cmd_disarm()
            await asyncio.sleep(0.2)
            assert cam.log == [("ToPos", 1)]                      # disarming does not move the camera
        finally:
            await S.ptz.close()
            await server.close()
            S.store.db.close()

    asyncio.run(run())
