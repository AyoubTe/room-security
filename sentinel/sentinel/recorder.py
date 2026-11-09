"""Camera ring buffer + event recording.

While the system is armed, one ffmpeg process copies the camera's main RTSP
stream (no re-encoding, so almost no CPU) into short .ts segments in RAM
(/dev/shm). Old segments are deleted, so RAM only ever holds a short
pre-roll. When an event starts we hold on to the segments from `preroll_s`
before the trigger. Once the alarm is confirmed, every `chunk_s` seconds the
finished segments are joined into an .mp4 "part" in the spool folder on the
SD card, and the uploader sends it to the cloud and deletes it.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from .camera import rtsp_input

log = logging.getLogger("sentinel.recorder")


@dataclass
class EventRec:
    id: str
    started: float
    t0: float               # keep segments that end after this moment
    folder: str
    uploading: bool = False
    part: int = 0
    consumed_upto: float = 0.0
    parts_made: int = 0
    snapshot_done: bool = False
    snap_tries: int = 0


def folder_name(started: float, event_id: str) -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(started)) + "_" + event_id.split("-")[-1]


class Recorder:
    def __init__(self, cfg: dict, uploader, clock=time.time):
        cam, cloud, paths = cfg["camera"], cfg["cloud"], cfg["paths"]
        self.ffmpeg = cam["ffmpeg"]
        self.segment_s = float(cam["segment_s"])
        self.preroll_s = float(cam["preroll_s"])
        self.chunk_s = float(cloud["chunk_s"])
        self.ring = Path(paths["ring_dir"])
        self.spool = Path(paths["data_dir"]) / "spool"
        self.input_args = list(cam.get("input_args") or rtsp_input(cam["rtsp_main"]))
        self.uploader = uploader
        self.clock = clock
        self.want = False
        self.proc: asyncio.subprocess.Process | None = None
        self.started_at = 0.0
        self.restart_delay = 5.0
        self.camera_ok = True
        self.event: EventRec | None = None

    # ------------------------------------------------------------ capture process
    def _alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def _start_proc(self) -> None:
        self.ring.mkdir(parents=True, exist_ok=True)
        self.spool.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin",
            *self.input_args,
            "-map", "0:v:0", "-map", "0:a?", "-c", "copy",
            "-f", "segment", "-segment_time", str(self.segment_s),
            "-segment_format", "mpegts", "-reset_timestamps", "1", "-strftime", "1",
            str(self.ring / "seg_%Y%m%d_%H%M%S.ts"),
        ]
        self.proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        self.started_at = self.clock()
        log.info("capture started (pid %s)", self.proc.pid)

    async def _stop_proc(self) -> None:
        if not self._alive():
            self.proc = None
            return
        self.proc.send_signal(signal.SIGINT)         # lets ffmpeg close the last segment cleanly
        try:
            await asyncio.wait_for(self.proc.wait(), 6)
        except asyncio.TimeoutError:
            self.proc.kill()
            await self.proc.wait()
        self.proc = None

    async def camera_on(self) -> None:
        self.want = True
        if not self._alive():
            await self._start_proc()

    async def camera_off(self) -> None:
        self.want = False
        await self._stop_proc()
        self._clear_ring()
        self.camera_ok = True

    def _clear_ring(self) -> None:
        if self.ring.exists():
            for p in self.ring.glob("seg_*.ts"):
                p.unlink(missing_ok=True)

    # ------------------------------------------------------------ segments
    def _segments(self) -> list[Path]:
        if not self.ring.exists():
            return []
        files = []
        for p in self.ring.glob("seg_*.ts"):
            try:
                files.append((p.stat().st_mtime, p.name, p))
            except FileNotFoundError:
                pass
        return [p for _, _, p in sorted(files)]

    def _complete(self, files: list[Path]) -> list[Path]:
        """All segments except the one ffmpeg is still writing."""
        return files[:-1] if (files and self._alive()) else files

    def _janitor(self) -> None:
        now = self.clock()
        keep_after = self.event.t0 if self.event else now - (self.preroll_s + 2 * self.segment_s)
        for p in self._segments():
            try:
                if p.stat().st_mtime < keep_after:
                    p.unlink(missing_ok=True)
            except FileNotFoundError:
                pass

    # ------------------------------------------------------------ events
    def event_start(self, event_id: str, started: float) -> None:
        self.event = EventRec(
            id=event_id, started=started, t0=started - self.preroll_s,
            folder=folder_name(started, event_id), consumed_upto=started - self.preroll_s,
        )

    async def event_alarm(self) -> None:
        if not self.event:
            return
        self.event.uploading = True
        await self._snapshot()
        await self._assemble(final=False)

    async def event_stop(self, stop_camera: bool) -> dict:
        ev = self.event
        if ev is None:
            if stop_camera:
                await self.camera_off()
            return {}
        if stop_camera:
            self.want = False
            await self._stop_proc()
        await self._assemble(final=True)
        self.event = None
        if stop_camera:
            self._clear_ring()
            self.camera_ok = True
        self.uploader.kick()
        return {"folder": ev.folder, "parts": ev.parts_made}

    async def event_cancel(self, stop_camera: bool) -> None:
        self.event = None
        if stop_camera:
            await self.camera_off()

    async def _snapshot(self) -> None:
        ev = self.event
        if not ev or ev.snapshot_done or ev.snap_tries >= 6:
            return
        files = self._complete(self._segments()) or self._segments()
        if not files:
            return
        ev.snap_tries += 1
        out_dir = self.spool / ev.folder
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = out_dir / "snapshot.jpg.tmp"
        for seek in (["-sseof", "-3"], []):
            proc = await asyncio.create_subprocess_exec(
                self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                *seek, "-i", str(files[-1]), "-frames:v", "1", "-q:v", "3",
                "-c:v", "mjpeg", "-update", "1", "-f", "image2", str(tmp),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                tmp.rename(out_dir / "snapshot.jpg")
                ev.snapshot_done = True
                return
        tmp.unlink(missing_ok=True)

    async def _concat(self, files: list[Path], dest_stem: Path) -> Path | None:
        list_file = dest_stem.with_suffix(".txt")
        list_file.write_text("".join(f"file '{p}'\n" for p in files), encoding="utf-8")
        try:
            for ext, fmt, extra in (("mp4", "mp4", ["-movflags", "+faststart"]), ("mkv", "matroska", [])):
                final = dest_stem.with_suffix("." + ext)
                tmp = final.with_name(final.name + ".tmp")
                proc = await asyncio.create_subprocess_exec(
                    self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-c", "copy", *extra, "-f", fmt, str(tmp),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                )
                _, err = await proc.communicate()
                if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                    tmp.rename(final)
                    return final
                log.warning("concat to %s failed: %s", ext, err.decode(errors="replace")[-200:])
                tmp.unlink(missing_ok=True)
            return None
        finally:
            list_file.unlink(missing_ok=True)

    async def _assemble(self, final: bool) -> None:
        ev = self.event
        if not ev or not ev.uploading:
            return
        files = [
            p for p in self._complete(self._segments())
            if p.exists() and p.stat().st_mtime > ev.consumed_upto
        ]
        if not files:
            return
        if not final and len(files) * self.segment_s < self.chunk_s:
            return
        out_dir = self.spool / ev.folder
        out_dir.mkdir(parents=True, exist_ok=True)
        ev.part += 1
        made = await self._concat(files, out_dir / f"part_{ev.part:03d}")
        if made is None:
            ev.part -= 1                      # keep the segments; retry on the next tick
            return
        ev.parts_made += 1
        ev.consumed_upto = max(p.stat().st_mtime for p in files if p.exists())
        for p in files:
            p.unlink(missing_ok=True)
        self.uploader.kick()

    # ------------------------------------------------------------ periodic
    async def tick(self) -> None:
        now = self.clock()
        if self.want:
            if not self._alive():
                self.camera_ok = False
                if now - self.started_at >= self.restart_delay:
                    self.restart_delay = min(30.0, self.restart_delay * 2)
                    try:
                        await self._start_proc()
                    except Exception as exc:  # pragma: no cover - spawn failure
                        log.error("cannot start capture: %s", exc)
            else:
                files = self._segments()
                grace = 3 * self.segment_s + 10
                fresh = bool(files) and (now - files[-1].stat().st_mtime) < 2 * self.segment_s + 10
                if fresh:
                    self.camera_ok = True
                    self.restart_delay = 5.0
                elif now - self.started_at > grace:
                    self.camera_ok = False
                    log.warning("capture stalled, restarting")
                    await self._stop_proc()
        self._janitor()
        if self.event and self.event.uploading:
            await self._snapshot()
            await self._assemble(final=False)

    def status(self) -> dict:
        return {
            "capturing": self._alive(),
            "event_id": self.event.id if self.event else None,
            "uploading": bool(self.event and self.event.uploading),
            "parts": self.event.parts_made if self.event else 0,
        }

    async def shutdown(self) -> None:
        if self.event and self.event.uploading:
            await self.event_stop(stop_camera=True)
        else:
            await self.camera_off()
