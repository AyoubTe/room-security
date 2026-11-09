"""Full-service test: API + engine + recorder + uploader, with a fake Zigbee bridge and fake camera."""

import asyncio
import copy
import time

from aiohttp.test_utils import TestClient, TestServer

from sentinel.api import build_app
from sentinel.config import DEFAULTS, validate
from sentinel.main import Sentinel
from sentinel.mqttio import parse_message, siren_payloads

AUTH = {"Authorization": "Bearer secret-token"}


class FakeZ2M:
    connected = True

    def __init__(self):
        self.sent = []

    def publish(self, name, payload):
        self.sent.append((name, payload))
        return True

    def start(self):
        pass

    def stop(self):
        pass


def make_cfg(tmp_path, sample=None, rclone=None):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["api"]["token"] = "secret-token"
    cfg["paths"] = {"data_dir": str(tmp_path / "data"), "ring_dir": str(tmp_path / "ring")}
    cfg["sensors"] = [
        {"name": "door", "z2m": "door_contact", "kind": "contact", "label": "Door", "entry_delay": True},
        {"name": "window", "z2m": "window_contact", "kind": "contact", "label": "Window"},
        {"name": "motion", "z2m": "motion", "kind": "motion", "label": "Motion", "entry_delay": True},
    ]
    cfg["timing"] = {"exit_delay_s": 1, "entry_delay_s": 1, "post_roll_s": 4, "baseline_s": 0}
    cfg["siren"].update({"duration_s": 3})
    cfg["camera"].update({"segment_s": 1, "preroll_s": 2})
    cfg["cloud"].update({"chunk_s": 2})
    if sample:
        cfg["camera"]["input_args"] = ["-re", "-stream_loop", "-1", "-i", str(sample)]
        cfg["camera"]["rtsp_sub"] = "unused"
    if rclone:
        cfg["cloud"].update({"remote": "fake:SecurityCam", "rclone": str(rclone)})
    validate(cfg)
    return cfg


def test_config_validation():
    cfg = copy.deepcopy(DEFAULTS)
    cfg["sensors"] = [{"name": "a", "z2m": "a", "kind": "contact"}]
    try:
        validate(cfg)
        raise AssertionError("empty token must be rejected")
    except ValueError as e:
        assert "token" in str(e)
    cfg["api"]["token"] = "x" * 20
    validate(cfg)
    cfg["sensors"][0]["kind"] = "smoke"
    try:
        validate(cfg)
        raise AssertionError("bad kind must be rejected")
    except ValueError:
        pass


def test_parse_zigbee2mqtt_messages():
    by = {"door_contact": "door", "motion": "motion"}
    p = lambda t, b: parse_message("zigbee2mqtt", by, t, b)  # noqa: E731
    assert p("zigbee2mqtt/door_contact", b'{"contact": false, "battery": 98}') == (
        "values", "door", {"contact": False, "battery": 98})
    assert p("zigbee2mqtt/door_contact/availability", b'{"state":"offline"}') == ("avail", "door", False)
    assert p("zigbee2mqtt/door_contact/availability", b"online") == ("avail", "door", True)
    assert p("zigbee2mqtt/bridge/state", b'{"state":"online"}') == ("bridge", True)
    assert p("zigbee2mqtt/bridge/state", b"offline") == ("bridge", False)
    assert p("zigbee2mqtt/other_device", b'{"contact": false}') is None
    assert p("zigbee2mqtt/door_contact", b"not json") is None
    assert p("zigbee2mqtt/door_contact", b'""') is None


def test_siren_payloads():
    snzb = DEFAULTS["siren"]
    on = siren_payloads(snzb, True, 60)
    assert on[0]["alarm_duration"] == 60 and on[0]["alarm_volume_level"] == "max"
    assert on[0]["alarm_sound_enable"] == "ON" and on[0]["alarm_light_enable"] == "ON"   # SNZB-09P is silent if these are OFF
    assert on[1] == {"siren_on": "ON"}
    old = {**snzb, "settings": {"alarm_sound_enable": True, "alarm_light_enable": False}}     # booleans from an old config
    assert siren_payloads(old, True, 5)[0]["alarm_sound_enable"] == "ON" and siren_payloads(old, True, 5)[0]["alarm_light_enable"] == "OFF"
    assert siren_payloads(snzb, False) == [{"siren_on": "OFF"}]
    warn = {**snzb, "type": "warning"}
    assert siren_payloads(warn, True, 30)[0]["warning"]["duration"] == 30
    assert siren_payloads(warn, False)[0]["warning"]["mode"] == "stop"


def test_api_auth_validation_and_open_window_flow(tmp_path):
    async def run():
        S = Sentinel(make_cfg(tmp_path), asyncio.get_running_loop(), mqtt=False)
        S.z2m = FakeZ2M()
        client = TestClient(TestServer(build_app(S)))
        await client.start_server()
        try:
            assert (await client.get("/api/health")).status == 200
            assert (await client.get("/api/status")).status == 401
            assert (await client.get("/api/status", headers={"Authorization": "Bearer nope"})).status == 401

            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["state"] == "disarmed" and len(st["sensors"]) == 3

            S.on_values("window", {"contact": False})
            r = await client.post("/api/arm", json={}, headers=AUTH)
            assert r.status == 409 and (await r.json())["error"] == "open_sensors"
            r = await client.post("/api/arm", json={"force": True}, headers=AUTH)
            assert r.status == 200
            r = await client.post("/api/arm", json={}, headers=AUTH)
            assert r.status == 409

            r = await client.post("/api/register", json={"token": "garbage"}, headers=AUTH)
            assert r.status == 400
            r = await client.post("/api/register", json={"token": "ExponentPushToken[abc123]"}, headers=AUTH)
            assert r.status == 200 and S.store.tokens() == ["ExponentPushToken[abc123]"]

            live = await (await client.get("/api/live", headers=AUTH)).json()
            assert live["hls"].startswith("http://127.0.0.1:1984/api/stream.m3u8")

            r = await client.post("/api/siren/test", headers=AUTH)
            assert r.status == 409                        # not allowed while armed
            await client.post("/api/disarm", headers=AUTH)
            r = await client.post("/api/siren/test", headers=AUTH)
            assert r.status == 200
            assert S.z2m.sent[0][1]["alarm_duration"] == 3
            assert S.z2m.sent[1][1] == {"siren_on": "ON"}
        finally:
            await client.close()
            S.store.db.close()

    asyncio.run(run())


def test_full_intrusion_flow_records_uploads_and_notifies(tmp_path, sample_video, fake_rclone):
    rclone, cloud = fake_rclone

    async def run():
        S = Sentinel(make_cfg(tmp_path, sample_video, rclone), asyncio.get_running_loop(), mqtt=False)
        S.z2m = FakeZ2M()
        pushes = []

        async def fake_send(level, title, body):
            pushes.append((level, title))
            return 1

        S.notifier.send = fake_send
        await S.start()
        client = TestClient(TestServer(build_app(S)))
        await client.start_server()
        try:
            assert (await client.post("/api/arm", json={}, headers=AUTH)).status == 200
            await asyncio.sleep(2.5)                                     # exit delay + ring fills
            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["state"] == "armed" and st["recording"]["capturing"]

            S.on_values("door", {"contact": False})                      # intruder opens the door
            await asyncio.sleep(0.3)
            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["state"] == "entry_delay" and st["remaining_s"] is not None

            await asyncio.sleep(2.5)                                     # nobody disarms -> alarm
            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["state"] == "alarm" and st["siren_active"] and st["recording"]["uploading"]
            assert S.z2m.sent[-1][1] == {"siren_on": "ON"}

            # the intruder keeps moving for a while: recording must continue past the post-roll
            for _ in range(5):
                S.on_values("motion", {"occupancy": True})
                await asyncio.sleep(1.5)
            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["state"] == "alarm"

            await asyncio.sleep(5.5)                                     # activity stops -> post-roll ends
            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["state"] == "armed" and st["recording"]["event_id"] is None

            # user disarms
            await client.post("/api/disarm", headers=AUTH)
            for _ in range(40):
                if not S.uploader.pending():
                    break
                await asyncio.sleep(0.5)
            assert not S.uploader.pending()

            levels = [p[0] for p in pushes]
            assert "alarm" in levels and ("warn", "Entry detected") in pushes

            ev = (await (await client.get("/api/events?limit=50", headers=AUTH)).json())["events"]
            kinds = [e["kind"] for e in ev]
            for k in ("arming", "armed", "trigger", "alarm", "alarm_end", "clips", "disarmed"):
                assert k in kinds, (k, kinds)
            clips = next(e for e in ev if e["kind"] == "clips")
            assert clips["data"]["parts"] >= 3

            parts = list(cloud.rglob("part_*.mp4"))
            assert len(parts) == clips["data"]["parts"]
            assert (parts[0].parent / "snapshot.jpg").exists()
            for _ in range(30):                                          # camera shutdown is asynchronous
                if not S.recorder._alive() and not list(S.recorder.ring.glob("seg_*.ts")):
                    break
                await asyncio.sleep(0.5)
            assert not S.recorder._alive()
            assert not list(S.recorder.ring.glob("seg_*.ts"))            # RAM buffer wiped after disarm
        finally:
            await client.close()
            await S.stop()
            S.store.db.close()

    asyncio.run(run())


def test_armed_state_survives_restart(tmp_path):
    async def run():
        loop = asyncio.get_running_loop()
        S = Sentinel(make_cfg(tmp_path), loop, mqtt=False)
        S.cmd_arm()
        S.engine.tick(time.time() + 5)
        S.flush()
        assert S.store.get("armed") == "1"
        S.store.db.close()
        S2 = Sentinel(make_cfg(tmp_path), loop, mqtt=False)
        S2.engine.restore(S2.store.get("armed") == "1", time.time())
        assert S2.engine.state == "armed"
        S2.store.db.close()

    asyncio.run(run())
