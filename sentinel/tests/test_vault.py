"""Recordings in the cloud: listing, streaming with seeking, nightly clean-up, vacation mode, camera views.

A tiny stand-in for rclone works on a local folder that plays the part of Google Drive.
"""

import asyncio
import json
import os
import sys
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from sentinel.api import build_app
from sentinel.cloudfs import CloudError, CloudFs, folder_time
from sentinel.main import Sentinel

from test_features import AUTH, TZ, Clock, FakeZ2M, at, cfg_for, run_to
from test_ptz import FakeCamera, camera_server

FAKE_RCLONE = r'''
import json, os, sys
root = os.environ["FAKE_DRIVE"]
args = sys.argv[1:]
flags = {"--config", "--offset", "--count", "--retries", "--low-level-retries", "--contimeout", "--timeout"}
pos, opts, i = [], {}, 0
while i < len(args):
    a = args[i]
    if a in flags:
        opts[a] = args[i + 1]; i += 2
    elif a.startswith("--"):
        opts[a] = True; i += 1
    else:
        pos.append(a); i += 1
cmd, rest = pos[0], pos[1:]
def path(remote):
    return os.path.join(root, remote.split(":", 1)[1])
if cmd == "lsjson":
    p = path(rest[0])
    if not os.path.isdir(p):
        sys.stderr.write("directory not found\n"); sys.exit(3)
    out = []
    for n in sorted(os.listdir(p)):
        full = os.path.join(p, n)
        isdir = os.path.isdir(full)
        if ("--dirs-only" in opts and not isdir) or ("--files-only" in opts and isdir):
            continue
        out.append({"Name": n, "Path": n, "IsDir": isdir, "Size": -1 if isdir else os.path.getsize(full)})
    print(json.dumps(out))
elif cmd == "purge":
    import shutil
    shutil.rmtree(path(rest[0]))
    open(os.path.join(root, "purge.log"), "a").write(rest[0] + " " + " ".join(k for k in opts if k.startswith("--drive")) + "\n")
elif cmd == "size":
    count = total = 0
    for d, _, files in os.walk(path(rest[0])):
        for f in files:
            count += 1; total += os.path.getsize(os.path.join(d, f))
    print(json.dumps({"count": count, "bytes": total}))
elif cmd == "cat":
    with open(path(rest[0]), "rb") as f:
        f.seek(int(opts.get("--offset", 0)))
        data = f.read(int(opts["--count"])) if "--count" in opts else f.read()
    sys.stdout.buffer.write(data)
else:
    sys.stderr.write("unsupported\n"); sys.exit(2)
'''

OLD = "2026-10-10_09-00-00_aaaa"        # about a month before "now"
RECENT = "2026-11-03_22-15-00_bbbb"      # a few days before "now"
NOW = "2026-11-06 10:00"


@pytest.fixture
def drive(tmp_path, monkeypatch):
    root = tmp_path / "drive"
    (root / "SecurityCam").mkdir(parents=True)
    script = tmp_path / "rclone_stub.py"
    script.write_text(FAKE_RCLONE)
    wrapper = tmp_path / "rclone"
    wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} {script} "$@"\n')
    wrapper.chmod(0o755)
    monkeypatch.setenv("FAKE_DRIVE", str(root))
    return wrapper, root / "SecurityCam"


def put(cam_dir, folder, **files):
    d = cam_dir / folder
    d.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (d / name.replace("_mp4", ".mp4").replace("_jpg", ".jpg")).write_bytes(data)
    return d


def cfg_cloud(tmp_path, wrapper):
    cfg = cfg_for(tmp_path)
    cfg["cloud"].update({"remote": "fake:SecurityCam", "rclone": str(wrapper)})
    return cfg


def test_cloudfs_lists_streams_ranges_and_refuses_odd_names(tmp_path, drive):
    wrapper, cam = drive
    put(cam, OLD, part_001_mp4=bytes(range(256)) * 4, snapshot_jpg=b"JPG")
    (cam / "Holiday photos").mkdir()                          # not an event folder: must be ignored

    async def run():
        fs = CloudFs(cfg_cloud(tmp_path, wrapper)["cloud"] and {"cloud": cfg_cloud(tmp_path, wrapper)["cloud"]})
        assert await fs.folders() == [OLD]
        files = await fs.files(OLD)
        assert [(f["name"], f["size"], f["kind"]) for f in files] == [("part_001.mp4", 1024, "video"), ("snapshot.jpg", 3, "image")]
        chunks = [c async for c in fs.stream(OLD, "part_001.mp4", 250, 12)]
        assert b"".join(chunks) == (bytes(range(256)) * 4)[250:262]
        for bad in ("../x.mp4", "a/b.mp4", ".hidden"):
            with pytest.raises(CloudError):
                [c async for c in fs.stream(OLD, bad, 0, None)]
        with pytest.raises(CloudError):
            await fs.purge("Holiday photos")
        with pytest.raises(CloudError):
            await fs.purge("..")
        assert (await fs.size())["bytes"] == 1027

    asyncio.run(run())


def test_folder_times_follow_the_local_timezone():
    assert folder_time("2026-11-07_13-11-49_a1b2", TZ) == at("2026-11-07 13:11")  + 49
    assert folder_time("Holiday photos", TZ) is None


def test_cleanup_deletes_only_old_event_folders_and_rows(tmp_path, drive):
    wrapper, cam = drive
    put(cam, OLD, part_001_mp4=b"x" * 100)
    put(cam, RECENT, part_001_mp4=b"y" * 100)
    (cam / "Other stuff").mkdir()
    (cam / "Other stuff" / "keep.txt").write_text("mine")

    async def run():
        clock = Clock(NOW)
        S = Sentinel(cfg_cloud(tmp_path, wrapper), asyncio.get_running_loop(), clock=clock, mqtt=False)
        S.z2m = FakeZ2M()
        S.store.add_log("alarm", "old alarm", "1-aaaa", ts=at("2026-10-10 09:00"))
        S.store.add_log("alarm", "recent alarm", "2-bbbb", ts=at("2026-11-03 22:15"))
        try:
            res = await S.cleanup()
            assert res["folders"] == 1 and res["rows"] == 1 and res["error"] is None and res["skipped"] is None
            assert not (cam / OLD).exists() and (cam / RECENT).exists()
            assert (cam / "Other stuff" / "keep.txt").exists()                 # never touches foreign folders
            assert [e["text"] for e in S.store.recent(10) if e["kind"] == "alarm"] == ["recent alarm"]
            # Drive trash would keep the space used, so the delete must bypass it
            assert "--drive-use-trash=false" in (cam.parent / "purge.log").read_text()
            r = S.retention()
            assert r["days"] == 15 and r["hold"] is False and r["usage"]["bytes"] == 104 and r["last"]["folders"] == 1   # 100 recent + 4 in the foreign folder

            S.update_settings({"cloud": {"retention_days": 2}})               # shorter keep time takes effect
            assert (await S.cleanup())["folders"] == 1 and not (cam / RECENT).exists()

            S.update_settings({"cloud": {"retention_days": 0}})               # 0 = keep everything
            put(cam, OLD, part_001_mp4=b"z")
            assert (await S.cleanup())["skipped"] == "keep_forever" and (cam / OLD).exists()
        finally:
            S.store.db.close()

    asyncio.run(run())


def test_cleanup_is_paused_on_vacation_but_can_be_forced(tmp_path, drive):
    wrapper, cam = drive
    put(cam, OLD, part_001_mp4=b"x")

    async def run():
        clock = Clock(NOW)
        S = Sentinel(cfg_cloud(tmp_path, wrapper), asyncio.get_running_loop(), clock=clock, mqtt=False)
        S.z2m = FakeZ2M()
        S.store.add_log("alarm", "old alarm", None, ts=at("2026-10-10 09:00"))
        try:
            assert S.cmd_vacation(True)["ok"]
            res = await S.cleanup()
            assert res["skipped"] == "vacation" and (cam / OLD).exists()
            assert any(e["text"] == "old alarm" for e in S.store.recent(20))     # alerts kept too
            assert S.retention()["hold"] is True

            S.cmd_vacation(False)                                                # back home: normal rules again
            assert (await S.cleanup())["folders"] == 1 and not (cam / OLD).exists()

            put(cam, OLD, part_001_mp4=b"x")
            S.cmd_vacation(True)
            assert (await S.cleanup(manual=True))["folders"] == 1                # "Clean up now" is an explicit order
        finally:
            S.store.db.close()

    asyncio.run(run())


def test_nightly_loop_runs_once_a_day_after_the_set_time(tmp_path, drive):
    wrapper, cam = drive
    put(cam, OLD, part_001_mp4=b"x")

    async def run():
        clock = Clock("2026-11-06 03:00")
        S = Sentinel(cfg_cloud(tmp_path, wrapper), asyncio.get_running_loop(), clock=clock, mqtt=False)
        S.z2m = FakeZ2M()
        calls = []
        real = S.cleanup

        async def spy(manual=False):
            calls.append(clock.t)
            return await real(manual)

        S.cleanup = spy
        orig_sleep = asyncio.sleep

        async def fast_sleep(_):
            raise asyncio.CancelledError                          # one pass of the loop per call

        try:
            import sentinel.main as m
            m.asyncio.sleep = fast_sleep
            for hhmm, expected in (("03:00", 0), ("03:31", 1), ("15:00", 1)):    # before the time / first run / not again
                clock.go(f"2026-11-06 {hhmm}")
                with pytest.raises(asyncio.CancelledError):
                    await S._cleanup_loop()
                assert len(calls) == expected, hhmm
            clock.go("2026-11-07 03:40")
            with pytest.raises(asyncio.CancelledError):
                await S._cleanup_loop()
            assert len(calls) == 2                                # next day: again
        finally:
            m.asyncio.sleep = orig_sleep
            S.store.db.close()

    asyncio.run(run())


def test_vacation_arms_around_the_clock_and_ends_cleanly(tmp_path):
    async def run():
        clock = Clock("2026-11-04 22:00")                         # a Wednesday evening, no schedule at all
        cfg = cfg_for(tmp_path)
        S = Sentinel(cfg, asyncio.get_running_loop(), clock=clock, mqtt=False)
        S.z2m = FakeZ2M()
        S.pushes = []
        S._push_task = lambda level, title, body: S.pushes.append((level, title))
        try:
            assert S.cmd_vacation(True, 7)["ok"]
            run_to(S, clock, "2026-11-04 22:02")
            assert S.engine.state in ("exit_delay", "armed") and S.engine.armed_by == "schedule"
            assert S.sched["state"] == "vacation" and S.sched["vacation"]["until"] == pytest.approx(clock.t + 7 * 86400, abs=300)
            run_to(S, clock, "2026-11-08 13:00")                  # a weekday afternoon: still armed, not a "window"
            assert S.engine.state == "armed"
            assert S.vacation_on()

            # someone with a key comes by and disarms: vacation does not re-arm behind their back
            S.cmd_disarm()
            run_to(S, clock, "2026-11-08 13:30")
            assert S.engine.state == "disarmed" and S.sched["state"] == "suspended"
            S.cmd_schedule_resume()
            run_to(S, clock, "2026-11-08 13:32")
            assert S.engine.state in ("exit_delay", "armed")

            # the planned return date passes: back to normal, disarmed, with a notice
            run_to(S, clock, "2026-11-12 0:01".replace(" 0:", " 00:"))
            assert not S.vacation_on() and S.engine.state == "disarmed"
            assert "Vacation mode ended" in [t for _, t in S.pushes]
            kinds = [e["kind"] for e in S.store.recent(100)]
            assert "vacation" in kinds

            # switching it off by hand disarms what vacation armed
            S.cmd_vacation(True)
            run_to(S, clock, "2026-11-12 00:05")
            assert S.engine.state in ("exit_delay", "armed")
            S.cmd_vacation(False)
            assert S.engine.state == "disarmed" and S.sched["state"] != "vacation"

            assert S.cmd_vacation("yes")["error"] == "bad_request"
            assert S.cmd_vacation(True, 0)["error"] == "bad_days"
            assert S.cmd_vacation(True, 400)["error"] == "bad_days"
        finally:
            S.store.db.close()

    asyncio.run(run())


def test_vacation_waits_while_a_sensor_is_open(tmp_path):
    async def run():
        clock = Clock("2026-11-04 22:00")
        S = Sentinel(cfg_for(tmp_path), asyncio.get_running_loop(), clock=clock, mqtt=False)
        S.z2m = FakeZ2M()
        try:
            S.on_values("window", {"contact": False})             # window left open
            S.cmd_vacation(True)
            run_to(S, clock, "2026-11-04 22:05")
            assert S.engine.state == "disarmed" and S.sched["state"] == "postponed"
            S.on_values("window", {"contact": True})
            run_to(S, clock, "2026-11-04 22:07")
            assert S.engine.state in ("exit_delay", "armed") and S.sched["state"] == "vacation"
        finally:
            S.store.db.close()

    asyncio.run(run())


def test_camera_turns_to_the_view_of_the_sensor_that_triggered(tmp_path):
    async def run():
        cam = FakeCamera()
        server = await camera_server(cam)
        clock = Clock("2026-11-04 22:00")
        cfg = cfg_for(tmp_path)
        cfg["camera"]["rtsp_sub"] = "rtsp://admin:test-camera-pass@127.0.0.1:554/Preview_01_sub"
        cfg["camera"]["ptz"]["port"] = server.port
        S = Sentinel(cfg, asyncio.get_running_loop(), clock=clock, mqtt=False)
        S.z2m = FakeZ2M()
        try:
            S.update_settings({"camera": {"views": {"door": 3, "window": 2, "motion": 1}}})
            S.cmd_arm(force=True)
            run_to(S, clock, "2026-11-04 22:02", step=5)
            assert S.engine.state == "armed"

            S.on_values("window", {"contact": False})             # window opened: immediate alarm
            await asyncio.sleep(0.4)
            assert cam.log == [("ToPos", 2)]
            S.on_values("window", {"contact": False})             # same sensor again: no pointless re-aim
            await asyncio.sleep(0.2)
            assert cam.log == [("ToPos", 2)]

            clock.plus(30)
            S.on_values("motion", {"occupancy": True})            # the intruder moves on to the centre
            await asyncio.sleep(0.4)
            assert cam.log == [("ToPos", 2), ("ToPos", 1)]
            assert any(e["kind"] == "camera" for e in S.store.recent(50))

            S.update_settings({"camera": {"follow": False}})
            clock.plus(60)
            S.on_values("door", {"contact": False})
            await asyncio.sleep(0.3)
            assert cam.log == [("ToPos", 2), ("ToPos", 1)]        # switched off: stays put

            S.update_settings({"camera": {"follow": True, "views": {"motion": None}}})
            assert "motion" not in S.settings["camera"]["views"] and S.settings["camera"]["views"]["door"] == 3
            for bad in ({"views": {"garage": 1}}, {"views": {"door": 99}}, {"follow": "yes"}):
                with pytest.raises(ValueError):
                    S.update_settings({"camera": bad})
        finally:
            await S.ptz.close()
            await server.close()
            S.store.db.close()

    asyncio.run(run())


def test_api_lists_clips_streams_ranges_and_runs_cleanup(tmp_path, drive):
    wrapper, cam = drive
    event_id = f"{int(at('2026-11-06 09:00'))}-a1b2"
    folder = "2026-11-06_09-00-00_a1b2"
    blob = bytes(range(256)) * 40
    put(cam, folder, part_001_mp4=blob, part_002_mp4=b"second", snapshot_jpg=b"JPEG")

    async def run():
        clock = Clock(NOW)
        S = Sentinel(cfg_cloud(tmp_path, wrapper), asyncio.get_running_loop(), clock=clock, mqtt=False)
        S.z2m = FakeZ2M()
        # one clip is still waiting on the Pi
        spool = tmp_path / "data" / "spool" / folder
        spool.mkdir(parents=True)
        (spool / "part_003.mp4").write_bytes(b"waiting")
        client = TestClient(TestServer(build_app(S)))
        await client.start_server()
        base = f"/api/events/{event_id}/clips"
        try:
            assert (await client.get(base)).status == 401
            info = await (await client.get(base, headers=AUTH)).json()
            assert info["folder"] == folder
            assert [(c["name"], c["where"]) for c in info["clips"]] == [
                ("part_001.mp4", "cloud"), ("part_002.mp4", "cloud"), ("part_003.mp4", "pi"), ("snapshot.jpg", "cloud")]

            r = await client.get(f"{base}/part_001.mp4", headers=AUTH)
            assert r.status == 200 and r.headers["Accept-Ranges"] == "bytes" and await r.read() == blob
            assert r.headers["Content-Type"] == "video/mp4"

            r = await client.get(f"{base}/part_001.mp4", headers={**AUTH, "Range": "bytes=100-199"})
            assert r.status == 206 and r.headers["Content-Range"] == f"bytes 100-199/{len(blob)}"
            assert await r.read() == blob[100:200]
            r = await client.get(f"{base}/part_001.mp4", headers={**AUTH, "Range": "bytes=10000-"})
            assert r.status == 206 and await r.read() == blob[10000:]
            r = await client.get(f"{base}/part_001.mp4", headers={**AUTH, "Range": "bytes=-50"})
            assert r.status == 206 and await r.read() == blob[-50:]
            assert (await client.get(f"{base}/part_001.mp4", headers={**AUTH, "Range": "bytes=99999-"})).status == 416

            r = await client.get(f"{base}/part_003.mp4", headers=AUTH)             # served from the Pi's own spool
            assert r.status == 200 and await r.read() == b"waiting"
            r = await client.get(f"{base}/snapshot.jpg", headers=AUTH)
            assert r.headers["Content-Type"] == "image/jpeg" and await r.read() == b"JPEG"

            for bad in ("nope.mp4", "..%2Fsecret.mp4", "notes.txt", "part_001.exe"):
                assert (await client.get(f"{base}/{bad}", headers=AUTH)).status == 404, bad
            assert (await client.get("/api/events/not-an-id/clips", headers=AUTH)).status == 404
            assert (await client.get("/api/events/123456789-ffff/clips/part_001.mp4", headers=AUTH)).status == 404

            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["retention"]["days"] == 15 and st["schedule"]["vacation"] == {"active": False, "since": None, "until": None}

            r = await (await client.post("/api/vacation", json={"active": True, "days": 14}, headers=AUTH)).json()
            assert r["ok"] and r["vacation"]["active"]
            assert (await client.post("/api/vacation", json={"active": "x"}, headers=AUTH)).status == 400
            st = await (await client.get("/api/status", headers=AUTH)).json()
            assert st["retention"]["hold"] is True

            r = await (await client.post("/api/cloud/cleanup", headers=AUTH)).json()
            assert r["ok"] and r["result"]["manual"] is True and (cam / folder).exists()   # recent: not deleted
        finally:
            await client.close()
            S.store.db.close()

    asyncio.run(run())


def test_camera_turns_back_after_the_intrusion_has_been_quiet(tmp_path):
    async def run():
        cam = FakeCamera()
        server = await camera_server(cam)
        clock = Clock("2026-11-04 22:00")
        cfg = cfg_for(tmp_path)
        cfg["camera"]["rtsp_sub"] = "rtsp://admin:test-camera-pass@127.0.0.1:554/Preview_01_sub"
        cfg["camera"]["ptz"]["port"] = server.port
        S = Sentinel(cfg, asyncio.get_running_loop(), clock=clock, mqtt=False)
        S.z2m = FakeZ2M()
        try:
            S.update_settings({"camera": {"views": {"window": 2, "motion": 1}, "return_view": 1, "return_after_s": 60}})
            assert S.settings["camera"]["return_view"] == 1 and S.settings["camera"]["return_after_s"] == 60
            for bad in ({"return_after_s": 5}, {"return_view": 99}):
                with pytest.raises(ValueError):
                    S.update_settings({"camera": bad})

            async def settle():
                await asyncio.sleep(0.3)

            S.cmd_arm(force=True)
            run_to(S, clock, "2026-11-04 22:02", step=5)
            S.on_values("window", {"contact": False})
            await settle()
            assert cam.log == [("ToPos", 2)]
            assert S.engine.state == "alarm"

            run_to(S, clock, "2026-11-04 22:04", step=5)           # alarm still going on: stays on the window
            await settle()
            assert cam.log == [("ToPos", 2)]

            S.cmd_disarm()                                         # the intrusion is over
            run_to(S, clock, "2026-11-04 22:04", step=5)
            clock.plus(30)
            S.tick_once()
            await settle()
            assert cam.log == [("ToPos", 2)]                       # not quiet for a minute yet
            clock.plus(40)
            S.tick_once()
            await settle()
            assert cam.log == [("ToPos", 2), ("ToPos", 1)]         # back to Centre
            assert any("back to saved view 1" in e["text"] for e in S.store.recent(50))
            clock.plus(300)
            S.tick_once()
            await settle()
            assert cam.log.count(("ToPos", 1)) == 1                # only once

            # someone turns the camera by hand while it is quiet: it is left alone
            S.cmd_arm(force=True)
            run_to(S, clock, "2026-11-04 23:00", step=5)
            S.on_values("window", {"contact": False})
            await settle()
            await S.ptz.goto(3)                                    # manual move from the app
            S.cmd_disarm()
            clock.plus(120)
            S.tick_once()
            await settle()
            assert cam.log[-1] == ("ToPos", 3)
        finally:
            await S.ptz.close()
            await server.close()
            S.store.db.close()

    asyncio.run(run())
