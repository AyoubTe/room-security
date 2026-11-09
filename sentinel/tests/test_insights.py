import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from aiohttp.test_utils import TestClient, TestServer

from sentinel import insights, system
from sentinel.api import build_app

from test_features import AUTH, at, make, run_to  # noqa: E402  (shared fake-clock helpers)

TZ = ZoneInfo("Europe/Paris")


def row(ts, kind, text="", data=None):
    return {"ts": at(ts) if isinstance(ts, str) else ts, "kind": kind, "text": text, "data": data}


NOW = at("2026-11-04 20:00")


def test_counts_per_day_hours_and_sensors():
    rows = [
        row("2026-11-02 14:10", "trigger", "Door opened", {"sensor": "door"}),
        row("2026-11-02 14:11", "alarm", "ALARM: Door opened"),
        row("2026-11-02 14:20", "clips", "2 clips", {"parts": 2}),
        row("2026-11-04 03:30", "trigger", "Motion", {"sensor": "motion"}),
        row("2026-11-04 03:31", "trigger", "Motion", {"sensor": "motion"}),
    ]
    r = insights.build(rows, NOW, TZ, 7, armed_now=False)
    assert [d["date"] for d in r["days"]][-1] == "2026-11-04" and len(r["days"]) == 7
    d2 = next(d for d in r["days"] if d["date"] == "2026-11-02")
    assert d2["alarms"] == 1 and d2["triggers"] == 1
    assert next(d for d in r["days"] if d["date"] == "2026-11-04")["triggers"] == 2
    assert r["hours"][14] == 2 and r["hours"][3] == 2
    assert r["by_sensor"] == [{"sensor": "motion", "count": 2}, {"sensor": "door", "count": 1}]
    assert r["totals"]["alarms"] == 1 and r["totals"]["clips"] == 2
    assert r["last_alarm"]["text"] == "ALARM: Door opened"


def test_events_outside_the_window_are_ignored():
    rows = [row("2026-10-01 10:00", "alarm", "old")]
    r = insights.build(rows, NOW, TZ, 7, armed_now=False)
    assert r["totals"]["alarms"] == 0 and r["last_alarm"] is None


def test_armed_time_is_split_across_midnight_and_counts_the_open_interval():
    rows = [
        row("2026-11-03 22:00", "arming"),
        row("2026-11-04 07:00", "disarmed"),         # 2 h on the 3rd, 7 h on the 4th
        row("2026-11-04 18:00", "arming"),           # still armed at 20:00 -> 2 h
    ]
    r = insights.build(rows, NOW, TZ, 7, armed_now=True)
    by = {d["date"]: d["armed_s"] for d in r["days"]}
    assert by["2026-11-03"] == 2 * 3600
    assert by["2026-11-04"] == 9 * 3600
    assert r["totals"]["armed_s"] == 11 * 3600
    assert 0 < r["totals"]["armed_pct"] < 100


def test_restored_after_restart_counts_as_armed():
    rows = [row("2026-11-04 12:00", "restored")]
    r = insights.build(rows, NOW, TZ, 3, armed_now=True)
    assert r["totals"]["armed_s"] == 8 * 3600


def test_system_snapshot_never_raises_and_has_the_expected_keys(tmp_path):
    s = system.snapshot(str(tmp_path))
    assert set(s) == {"cpu_temp_c", "load1", "mem_used_pct", "disk_used_pct", "disk_free_gb", "host_uptime_s"}
    assert s["disk_used_pct"] is not None and 0 <= s["disk_used_pct"] <= 100
    assert system.snapshot("/definitely/not/here")["disk_used_pct"] is None


def test_service_endpoint_reports_real_activity_and_link_quality(tmp_path):
    async def run():
        S, clock = make(tmp_path, "2026-11-04 12:00")
        client = TestClient(TestServer(build_app(S)))
        await client.start_server()
        try:
            S.on_values("window", {"contact": True, "linkquality": 180})
            S.cmd_arm()
            run_to(S, clock, "2026-11-04 12:10")
            S.on_values("window", {"contact": False})                    # intrusion
            run_to(S, clock, "2026-11-04 12:20")
            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["system"]["disk_used_pct"] is not None
            assert next(s for s in st["sensors"] if s["name"] == "window")["linkquality"] == 180

            r = await client.get("/api/insights?days=7", headers=AUTH)
            assert r.status == 200
            body = await r.json()
            today = body["days"][-1]
            assert today["date"] == "2026-11-04" and today["alarms"] == 1 and today["triggers"] == 1
            assert today["armed_s"] >= 20 * 60
            assert body["by_sensor"] == [{"sensor": "window", "count": 1}]
            assert body["hours"][12] == 2
            assert (await client.get("/api/insights?days=bogus", headers=AUTH)).status == 200
            assert len((await (await client.get("/api/insights?days=999", headers=AUTH)).json())["days"]) == 60
            assert (await client.get("/api/insights")).status == 401
        finally:
            await client.close()
            S.store.db.close()

    asyncio.run(run())
