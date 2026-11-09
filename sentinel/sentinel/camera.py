"""Camera helpers: single JPEG frames via ffmpeg."""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("sentinel.camera")


async def grab_jpeg(ffmpeg: str, input_args: list[str], timeout: float = 12.0) -> bytes | None:
    """Decode one frame from `input_args` (e.g. ["-rtsp_transport","tcp","-i",url]) as JPEG bytes."""
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        *input_args, "-frames:v", "1", "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "-",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            log.warning("snapshot timed out")
            return None
    except FileNotFoundError:
        log.error("ffmpeg not found: %s", ffmpeg)
        return None
    if proc.returncode != 0 or not out:
        log.warning("snapshot failed: %s", err.decode(errors="replace")[-200:])
        return None
    return out


def rtsp_input(url: str) -> list[str]:
    return ["-rtsp_transport", "tcp", "-timeout", "8000000", "-i", url]
