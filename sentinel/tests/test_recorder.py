"""End-to-end test of capture -> pre-roll -> parts -> upload, with a looped file as the 'camera'."""

import asyncio
import copy
import time

from sentinel.config import DEFAULTS
from sentinel.recorder import Recorder
from sentinel.uploader import Uploader


def make_cfg(tmp_path, sample, rclone):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["paths"] = {"data_dir": str(tmp_path / "data"), "ring_dir": str(tmp_path / "ring")}
    cfg["camera"].update({
        "segment_s": 1, "preroll_s": 2,
        "input_args": ["-re", "-stream_loop", "-1", "-i", str(sample)],
    })
    cfg["cloud"].update({"remote": "fake:SecurityCam", "rclone": str(rclone), "chunk_s": 2})
    return cfg


async def wait_for(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        await asyncio.sleep(0.25)
    return False


def test_pipeline_records_preroll_and_uploads(tmp_path, sample_video, fake_rclone):
    rclone, cloud = fake_rclone
    cfg = make_cfg(tmp_path, sample_video, rclone)

    async def run():
        up = Uploader(cfg, tmp_path / "data" / "spool")
        rec = Recorder(cfg, up)
        task = asyncio.create_task(up.run())
        await rec.camera_on()
        assert await wait_for(lambda: len(rec._segments()) >= 4)      # ring is filling
        # ring must not grow without bound while no event is active
        for _ in range(6):
            await rec.tick()
            await asyncio.sleep(1)
        assert len(rec._segments()) <= 6

        rec.event_start("100-abcd", time.time())
        await asyncio.sleep(1)
        await rec.event_alarm()                                        # alarm confirmed
        for _ in range(8):                                             # event runs ~8 s
            await rec.tick()
            await asyncio.sleep(1)
        info = await rec.event_stop(stop_camera=True)
        assert info["parts"] >= 2
        assert not rec._alive()
        assert not list(rec.ring.glob("seg_*.ts"))                     # RAM buffer wiped when disarmed

        assert await wait_for(lambda: not up.pending(), 20)
        up.stop()
        task.cancel()
        folders = [p for p in cloud.rglob("*") if p.is_dir()]
        assert len(folders) == 1 + 1                                   # SecurityCam + the event folder
        files = sorted(p.name for p in cloud.rglob("*") if p.is_file())
        assert "snapshot.jpg" in files
        parts = [f for f in files if f.startswith("part_")]
        assert len(parts) == info["parts"]
        assert all(f.endswith(".mp4") for f in parts)
        return cloud

    cloud_dir = asyncio.run(run())
    # The event ran ~9 s after the trigger and the pre-roll adds ~2 s before it, so the uploaded
    # parts together must cover at least ~9 s of video with no big gaps.
    import subprocess
    total = 0.0
    for part in sorted(cloud_dir.rglob("part_*.mp4")):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(part)],
            capture_output=True, text=True,
        ).stdout.strip()
        total += float(out)
    assert total >= 9.0, total


def test_cancelled_event_uploads_nothing(tmp_path, sample_video, fake_rclone):
    rclone, cloud = fake_rclone
    cfg = make_cfg(tmp_path, sample_video, rclone)

    async def run():
        up = Uploader(cfg, tmp_path / "data" / "spool")
        rec = Recorder(cfg, up)
        await rec.camera_on()
        assert await wait_for(lambda: len(rec._segments()) >= 2)
        rec.event_start("200-beef", time.time())
        await asyncio.sleep(2)
        await rec.event_cancel(stop_camera=True)
        await up.run_once()
        return up.pending()

    assert asyncio.run(run()) == []
    assert not list(cloud.rglob("*.mp4"))


def test_uploader_keeps_files_when_cloud_fails_and_retries(tmp_path, fake_rclone):
    rclone, cloud = fake_rclone
    cfg = copy.deepcopy(DEFAULTS)
    cfg["cloud"].update({"remote": "fake:SecurityCam", "rclone": "/bin/false"})
    spool = tmp_path / "spool"
    (spool / "evt").mkdir(parents=True)
    f = spool / "evt" / "part_001.mp4"
    f.write_bytes(b"x" * 100)
    failures = []

    async def run():
        up = Uploader(cfg, spool, on_failing=lambda e: failures.append(e))
        for _ in range(5):
            assert await up.run_once() is False
        assert f.exists() and failures                                 # kept, and user warned once
        assert up.status()["pending_files"] == 1
        up.rclone = str(rclone)                                        # internet is back
        assert await up.run_once() is True
        assert not f.exists()
        assert (cloud / "SecurityCam" / "evt" / "part_001.mp4").exists()

    asyncio.run(run())


def test_capture_restarts_after_camera_dies_and_flags_offline(tmp_path, sample_video, fake_rclone):
    rclone, _ = fake_rclone
    cfg = make_cfg(tmp_path, sample_video, rclone)
    cfg["camera"]["input_args"] = ["-i", "/nonexistent/file.mp4"]      # camera unreachable

    async def run():
        up = Uploader(cfg, tmp_path / "data" / "spool")
        rec = Recorder(cfg, up)
        await rec.camera_on()
        await asyncio.sleep(1.5)
        await rec.tick()
        ok = rec.camera_ok
        await rec.camera_off()
        return ok

    assert asyncio.run(run()) is False
