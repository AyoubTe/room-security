"""Schedule, silent siren and sensor bypass, driven through the real service with a fake clock."""

import asyncio
import copy
from datetime import datetime
from zoneinfo import ZoneInfo

from aiohttp.test_utils import TestClient, TestServer

from sentinel.api import build_app
from sentinel.config import DEFAULTS, validate
from sentinel.main import Sentinel

TZ = ZoneInfo("Europe/Paris")
AUTH = {"Authorization": "Bearer secret-token"}
WORK = {"days": [0, 1, 2, 3, 4], "start": "08:30", "end": "18:00"}      # 2026-11-04 is a Wednesday


def at(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=TZ).timestamp()


class Clock:
    def __init__(self, text):
        self.t = at(text)

    def __call__(self):
        return self.t

    def go(self, text):
        self.t = at(text)

    def plus(self, seconds):
        self.t += seconds


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


def cfg_for(tmp_path):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["api"]["token"] = "secret-token"
    cfg["timezone"] = "Europe/Paris"
    cfg["paths"] = {"data_dir": str(tmp_path / "data"), "ring_dir": str(tmp_path / "ring")}
    cfg["sensors"] = [
        {"name": "door", "z2m": "door_contact", "kind": "contact", "label": "Door", "entry_delay": True},
        {"name": "window", "z2m": "window_contact", "kind": "contact", "label": "Window"},
        {"name": "motion", "z2m": "motion", "kind": "motion", "label": "Motion", "entry_delay": True},
    ]
    cfg["timing"] = {"exit_delay_s": 30, "entry_delay_s": 20, "post_roll_s": 600, "baseline_s": 0}
    validate(cfg)
    return cfg


def make(tmp_path, start="2026-11-04 08:00"):
    clock = Clock(start)
    S = Sentinel(cfg_for(tmp_path), asyncio.get_running_loop(), clock=clock, mqtt=False)
    S.z2m = FakeZ2M()
    S.pushes = []
    S._push_task = lambda level, title, body: S.pushes.append((level, title))
    return S, clock


def titles(S):
    return [t for _, t in S.pushes]


def log_kinds(S):
    return [e["kind"] for e in S.store.recent(100)]


def run_to(S, clock, text, step=60):
    """Advance the fake clock to `text`, ticking the service as the real loop would."""
    target = at(text)
    while clock.t < target:
        clock.t = min(target, clock.t + step)
        S.tick_once()


def work_schedule(S, **extra):
    S.update_settings({"schedule": {"enabled": True, "windows": [WORK], **extra}})


def test_schedule_arms_at_start_warns_before_and_disarms_at_end(tmp_path):
    async def run():
        S, clock = make(tmp_path)
        work_schedule(S)
        run_to(S, clock, "2026-11-04 08:19")
        assert "Auto-arm at 08:30" not in titles(S)
        run_to(S, clock, "2026-11-04 08:21")
        assert titles(S).count("Auto-arm at 08:30") == 1
        run_to(S, clock, "2026-11-04 08:29")
        assert S.engine.state == "disarmed" and S.sched["state"] == "idle"
        run_to(S, clock, "2026-11-04 08:30")
        assert S.engine.state == "exit_delay" and S.engine.armed_by == "schedule"
        run_to(S, clock, "2026-11-04 09:00")
        assert S.engine.state == "armed" and S.sched["state"] == "armed"
        assert titles(S).count("Auto-arm at 08:30") == 1                 # one heads-up only
        run_to(S, clock, "2026-11-04 17:59")
        assert S.engine.state == "armed"
        run_to(S, clock, "2026-11-04 18:01")
        assert S.engine.state == "disarmed" and "Disarmed" in titles(S)
        assert S.sched["next_start"] == at("2026-11-05 08:30")
        assert S.store.get("armed") == "0"
        S.store.db.close()

    asyncio.run(run())


def test_skipped_day_and_home_weekday_do_not_arm(tmp_path):
    async def run():
        S, clock = make(tmp_path)
        work_schedule(S)
        assert S.cmd_schedule_skip("today", True)["ok"]
        run_to(S, clock, "2026-11-04 12:00")
        assert S.engine.state == "disarmed" and S.sched["state"] == "skipped"
        run_to(S, clock, "2026-11-05 09:00")                              # tomorrow is a normal day
        assert S.engine.state == "armed" and S.engine.armed_by == "schedule"

        S.cmd_disarm()
        S.cmd_schedule_resume()
        S.update_settings({"schedule": {"home_weekdays": [4]}})           # Fridays at home
        run_to(S, clock, "2026-11-06 12:00")
        assert S.engine.state == "disarmed" and S.sched["state"] == "skipped"
        run_to(S, clock, "2026-11-09 09:00")                              # Monday
        assert S.engine.state == "armed"
        S.store.db.close()

    asyncio.run(run())


def test_marking_today_as_home_disarms_a_schedule_armed_room_and_can_be_undone(tmp_path):
    async def run():
        S, clock = make(tmp_path)
        work_schedule(S)
        run_to(S, clock, "2026-11-04 09:00")
        assert S.engine.state == "armed"
        S.cmd_schedule_skip("today", True)
        run_to(S, clock, "2026-11-04 09:01")
        assert S.engine.state == "disarmed"
        S.cmd_schedule_skip("today", False)
        run_to(S, clock, "2026-11-04 09:02")
        assert S.engine.state in ("exit_delay", "armed")
        S.store.db.close()

    asyncio.run(run())


def test_manual_disarm_inside_window_suspends_until_resume_or_next_window(tmp_path):
    async def run():
        S, clock = make(tmp_path)
        work_schedule(S)
        run_to(S, clock, "2026-11-04 09:00")
        res = S.cmd_disarm()
        assert res["schedule_suspended"] is True
        run_to(S, clock, "2026-11-04 12:00")
        assert S.engine.state == "disarmed" and S.sched["state"] == "suspended"
        S.cmd_schedule_resume()
        run_to(S, clock, "2026-11-04 12:01")
        assert S.engine.state in ("exit_delay", "armed")
        S.cmd_disarm()
        run_to(S, clock, "2026-11-04 17:00")
        assert S.engine.state == "disarmed"
        run_to(S, clock, "2026-11-05 09:00")                              # a new window: normal again
        assert S.engine.state == "armed"
        S.store.db.close()

    asyncio.run(run())


def test_pause_blocks_auto_arm_until_it_expires(tmp_path):
    async def run():
        S, clock = make(tmp_path)
        work_schedule(S)
        S.cmd_schedule_pause(120)                                          # 08:00 + 2 h
        run_to(S, clock, "2026-11-04 09:59")
        assert S.engine.state == "disarmed" and S.sched["state"] == "paused"
        run_to(S, clock, "2026-11-04 10:01")
        assert S.engine.state in ("exit_delay", "armed")
        assert S.settings["schedule"]["paused_until"] is None
        assert S.cmd_schedule_pause(-5)["ok"] is False
        S.store.db.close()

    asyncio.run(run())


def test_manual_arm_is_never_auto_disarmed(tmp_path):
    async def run():
        S, clock = make(tmp_path, "2026-11-04 19:00")
        work_schedule(S)
        S.cmd_arm()
        run_to(S, clock, "2026-11-05 07:00")
        assert S.engine.state == "armed" and S.engine.armed_by == "user"
        run_to(S, clock, "2026-11-05 19:00")                               # window came and went
        assert S.engine.state == "armed"
        S.store.db.close()

    asyncio.run(run())


def test_smart_arm_waits_for_the_room_to_be_quiet(tmp_path):
    async def run():
        S, clock = make(tmp_path)
        work_schedule(S)
        run_to(S, clock, "2026-11-04 08:28")
        S.on_values("motion", {"occupancy": True})                         # you are at the PC
        run_to(S, clock, "2026-11-04 08:31")
        assert S.engine.state == "disarmed" and S.sched["state"] == "postponed"
        assert "Movement" in S.sched["reason"]
        run_to(S, clock, "2026-11-04 08:32")
        assert S.engine.state == "disarmed"                                # 08:28 + 300 s = 08:33
        S.on_values("motion", {"occupancy": True})                         # still moving at 08:32
        run_to(S, clock, "2026-11-04 08:36")
        assert S.engine.state == "disarmed"
        run_to(S, clock, "2026-11-04 08:38")                               # 300 s of calm have passed (08:37)
        assert S.engine.state in ("exit_delay", "armed")
        assert titles(S).count("Auto-arm postponed") == 1                  # told once, not every second
        S.store.db.close()

    asyncio.run(run())


def test_smart_arm_can_be_turned_off(tmp_path):
    async def run():
        S, clock = make(tmp_path)
        work_schedule(S, smart_arm=False)
        run_to(S, clock, "2026-11-04 08:29")
        S.on_values("motion", {"occupancy": True})
        run_to(S, clock, "2026-11-04 08:31")
        assert S.engine.state in ("exit_delay", "armed") and S.engine.armed_by == "schedule"
        S.store.db.close()

    asyncio.run(run())


def test_open_door_postpones_auto_arm_but_a_switched_off_window_does_not(tmp_path):
    async def run():
        S, clock = make(tmp_path)
        work_schedule(S)
        S.on_values("window", {"contact": False})                          # window left open
        run_to(S, clock, "2026-11-04 08:31")
        assert S.engine.state == "disarmed" and "Window open" in S.sched["reason"]
        S.cmd_sensor("window", False)                                      # I want the air: turn it off
        run_to(S, clock, "2026-11-04 08:32")
        assert S.engine.state in ("exit_delay", "armed")
        assert S.engine.sensors["window"].bypassed
        S.store.db.close()

    asyncio.run(run())


def test_quiet_hours_make_alarms_silent_and_daytime_alarms_loud(tmp_path):
    async def run():
        S, clock = make(tmp_path, "2026-11-04 12:00")
        S.update_settings({"siren": {"mode": "quiet_hours", "quiet_hours": {"start": "22:00", "end": "07:00"}}})
        S.cmd_arm()
        run_to(S, clock, "2026-11-04 23:00")
        S.tick_once()
        assert S.engine.state == "armed" and S.engine.silent
        S.on_values("window", {"contact": False})                          # night intrusion
        assert S.engine.state == "alarm"
        assert S.siren_queue.empty()                                       # nothing sent to the siren
        assert S.status()["alarm_silent"] is True
        assert ("alarm", "INTRUSION ALARM (silent)") in S.pushes
        assert any(e["kind"] == "alarm" and "silent" in e["text"] for e in S.store.recent(20))
        assert any(f[0] == "rec_alarm" for f in list(S.queue._queue))      # footage still recorded and uploaded

        S.cmd_disarm()
        S.on_values("window", {"contact": True})
        assert S.cmd_arm()["ok"]
        run_to(S, clock, "2026-11-05 12:00")
        while not S.siren_queue.empty():                                   # drop the disarm's "siren off"
            S.siren_queue.get_nowait()
        S.on_values("window", {"contact": False})                          # same intrusion in daytime
        assert S.engine.state == "alarm" and not S.engine.alarm_silent
        assert S.siren_queue.get_nowait() is True
        S.store.db.close()

    asyncio.run(run())


def test_silent_mode_overrides_everything_and_test_siren_still_works(tmp_path):
    async def run():
        S, clock = make(tmp_path, "2026-11-04 12:00")
        S.update_settings({"siren": {"mode": "silent", "volume": "low", "duration_s": 20}})
        assert S.effective()["siren_duration_s"] == 20
        assert (await S.cmd_siren_test())["ok"]
        assert S.z2m.sent[0][1]["alarm_volume_level"] == "low"             # runtime volume reaches the siren
        S.cmd_arm()
        run_to(S, clock, "2026-11-04 12:05")
        S.on_values("window", {"contact": False})
        assert S.engine.state == "alarm" and S.siren_queue.empty()
        S.store.db.close()

    asyncio.run(run())


def test_silence_siren_from_the_app_stops_it_without_ending_the_alarm(tmp_path):
    async def run():
        S, clock = make(tmp_path, "2026-11-04 12:00")
        S.cmd_arm()
        run_to(S, clock, "2026-11-04 12:05")
        S.on_values("window", {"contact": False})
        assert S.siren_queue.get_nowait() is True
        client = TestClient(TestServer(build_app(S)))
        await client.start_server()
        try:
            r = await client.post("/api/siren/silence", headers=AUTH)
            assert r.status == 200
            assert S.siren_queue.get_nowait() is False
            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["state"] == "alarm" and st["siren_active"] is False and st["event"] is not None
            r = await client.post("/api/siren/silence", headers=AUTH)
            assert r.status == 409
        finally:
            await client.close()
            S.store.db.close()

    asyncio.run(run())


def test_ventilate_window_for_a_while_then_it_protects_again(tmp_path):
    async def run():
        S, clock = make(tmp_path, "2026-11-04 12:00")
        S.cmd_arm()
        run_to(S, clock, "2026-11-04 12:05")
        assert S.cmd_sensor("window", False, minutes=60)["ok"]
        S.on_values("window", {"contact": False})                          # fresh air
        assert S.engine.state == "armed"
        S.on_values("door", {"contact": False})                            # the door is still guarded
        assert S.engine.state == "entry_delay"
        S.cmd_disarm()
        S.on_values("door", {"contact": True})
        assert S.cmd_arm()["ok"]
        run_to(S, clock, "2026-11-04 13:00")
        assert S.engine.sensors["window"].bypassed
        run_to(S, clock, "2026-11-04 13:07")                               # timer ran out, window still open
        assert not S.engine.sensors["window"].bypassed
        assert S.settings["sensors"]["window"]["enabled"] is True
        assert ("warn", "Window still open") in S.pushes
        S.store.db.close()

    asyncio.run(run())


def test_ventilate_until_closed(tmp_path):
    async def run():
        S, clock = make(tmp_path, "2026-11-04 12:00")
        S.cmd_arm()
        run_to(S, clock, "2026-11-04 12:05")
        S.cmd_sensor("window", False, until_closed=True)                   # window is closed right now
        run_to(S, clock, "2026-11-04 12:20")
        assert S.engine.sensors["window"].bypassed                         # waiting for it to be opened first
        S.on_values("window", {"contact": False})
        run_to(S, clock, "2026-11-04 14:00")
        assert S.engine.sensors["window"].bypassed and S.engine.state == "armed"
        S.on_values("window", {"contact": True})                           # I closed it
        run_to(S, clock, "2026-11-04 14:01")
        assert not S.engine.sensors["window"].bypassed
        assert ("info", "Window sensor active") in S.pushes
        S.on_values("window", {"contact": False})                          # now it counts again
        assert S.engine.state == "alarm"
        S.store.db.close()

    asyncio.run(run())


def test_door_off_window_on_and_back_with_permanent_switch(tmp_path):
    async def run():
        S, clock = make(tmp_path, "2026-11-04 12:00")
        assert S.cmd_sensor("door", False)["ok"]                           # until I turn it back on
        S.cmd_arm()
        run_to(S, clock, "2026-11-05 12:00")
        assert S.engine.sensors["door"].bypassed
        S.on_values("door", {"contact": False})
        assert S.engine.state == "armed"
        S.on_values("window", {"contact": False})
        assert S.engine.state == "alarm"
        assert S.cmd_sensor("door", True)["ok"] and not S.engine.sensors["door"].bypassed
        assert S.cmd_sensor("garage", True) == {"ok": False, "error": "unknown_sensor"}
        assert S.cmd_sensor("door", False, minutes=0)["ok"] is False           # 0 is not a valid timer
        S.store.db.close()

    asyncio.run(run())


def test_settings_and_state_survive_a_restart(tmp_path):
    async def run():
        S, clock = make(tmp_path)
        work_schedule(S, skip_dates=["2026-11-05"])
        S.update_settings({"siren": {"mode": "quiet_hours"}, "timing": {"exit_delay_s": 90}})
        S.cmd_sensor("window", False)
        run_to(S, clock, "2026-11-04 09:00")
        assert S.engine.state == "armed"
        S.store.db.close()

        S2, _ = make(tmp_path, "2026-11-04 09:05")
        S2.engine.restore(S2.store.get("armed") == "1", S2.clock(), S2.store.get("armed_by") or "user")
        assert S2.settings["schedule"]["windows"] == [{"days": [0, 1, 2, 3, 4], "start": "08:30", "end": "18:00"}]
        assert S2.settings["siren"]["mode"] == "quiet_hours" and S2.engine.t.exit_delay_s == 90
        assert S2.engine.sensors["window"].bypassed
        assert S2.engine.state == "armed" and S2.engine.armed_by == "schedule"   # and still auto-disarms later
        run_to(S2, S2.clock, "2026-11-04 18:01")
        assert S2.engine.state == "disarmed"
        S2.store.db.close()

    asyncio.run(run())


def test_api_settings_sensors_schedule_and_status(tmp_path):
    async def run():
        S, clock = make(tmp_path)
        client = TestClient(TestServer(build_app(S)))
        await client.start_server()
        try:
            assert (await client.get("/api/settings")).status == 401
            r = await client.get("/api/settings", headers=AUTH)
            body = await r.json()
            assert r.status == 200 and body["timezone"] == "Europe/Paris" and body["settings"]["schedule"]["enabled"] is False

            r = await client.post("/api/settings", json={"schedule": {"windows": [{"days": [], "start": "08:00", "end": "09:00"}]}}, headers=AUTH)
            assert r.status == 400 and "day" in (await r.json())["detail"]
            r = await client.post("/api/settings", json={"schedule": {"enabled": True, "windows": [WORK]}}, headers=AUTH)
            assert r.status == 200 and (await r.json())["settings"]["schedule"]["enabled"] is True
            S.tick_once()

            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["schedule"]["state"] == "idle" and st["schedule"]["next_start"] == at("2026-11-04 08:30")
            assert st["siren_mode"] == "on" and st["timezone"] == "Europe/Paris"
            assert all(s["enabled"] for s in st["sensors"])

            r = await client.post("/api/sensors/window", json={"enabled": False, "minutes": 90}, headers=AUTH)
            assert r.status == 200 and (await r.json())["sensor"]["until"] == clock.t + 5400
            r = await client.post("/api/sensors/window", json={"enabled": "no"}, headers=AUTH)
            assert r.status == 400
            r = await client.post("/api/sensors/window", json={"enabled": False, "minutes": 99999}, headers=AUTH)
            assert r.status == 400
            r = await client.post("/api/sensors/garage", json={"enabled": False}, headers=AUTH)
            assert r.status == 404
            st = await (await client.get("/api/status", headers=AUTH)).json()
            win = next(s for s in st["sensors"] if s["name"] == "window")
            assert win["enabled"] is False and win["bypassed"] is True and win["bypass_until"] == clock.t + 5400

            r = await client.post("/api/schedule/skip", json={"date": "today"}, headers=AUTH)
            assert (await r.json()) == {"ok": True, "date": "2026-11-04", "skipped": True}
            r = await client.post("/api/schedule/skip", json={"date": "someday"}, headers=AUTH)
            assert r.status == 400
            S.tick_once()
            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["schedule"]["state"] == "idle" or st["schedule"]["state"] == "skipped"
            r = await client.post("/api/schedule/pause", json={"minutes": 30}, headers=AUTH)
            assert r.status == 200
            r = await client.post("/api/schedule/pause", json={"minutes": "x"}, headers=AUTH)
            assert r.status == 400
            assert (await client.post("/api/schedule/resume", headers=AUTH)).status == 200
            assert S.settings["schedule"]["paused_until"] is None
        finally:
            await client.close()
            S.store.db.close()

    asyncio.run(run())
