"""Reading and cleaning the cloud folder (Google Drive via rclone).

Every event lives in its own folder directly under the remote:
    <remote>/2026-11-07_13-11-49_a1b2/part_001.mp4, part_002.mp4, snapshot.jpg

This module lists those folders and files, streams a file (with HTTP-style byte ranges, so the phone
can seek), deletes whole event folders and measures the space used. It never touches anything that
is not an event folder: folder names must match FOLDER_RE exactly, so a wrong remote path cannot
turn a clean-up into "delete my Drive".
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, tzinfo
from typing import AsyncIterator

log = logging.getLogger("sentinel.cloudfs")

FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_[0-9a-f]{4}$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")
VIDEO_EXT = (".mp4", ".mkv")
IMAGE_EXT = (".jpg", ".jpeg")
MIME = {".mp4": "video/mp4", ".mkv": "video/x-matroska", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
CACHE_S = 60.0


class CloudError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def folder_time(name: str, tz: tzinfo) -> float | None:
    """Start time encoded in an event folder name, or None if it is not one of ours."""
    if not FOLDER_RE.match(name):
        return None
    return datetime.strptime(name[:19], "%Y-%m-%d_%H-%M-%S").replace(tzinfo=tz).timestamp()


def ext_of(name: str) -> str:
    return name[name.rfind("."):].lower() if "." in name else ""


def clip_kind(name: str) -> str | None:
    e = ext_of(name)
    return "video" if e in VIDEO_EXT else "image" if e in IMAGE_EXT else None


class CloudFs:
    def __init__(self, cfg: dict, clock=time.time):
        cloud = cfg["cloud"]
        self.remote = (cloud.get("remote") or "").rstrip("/")
        self.rclone = cloud["rclone"]
        self.config = cloud.get("rclone_config") or ""
        self.extra = list(cloud.get("extra_args") or [])
        # Google Drive keeps deleted files in its trash, which still counts against the quota.
        self.purge_args = list(cloud.get("purge_args") if cloud.get("purge_args") is not None else ["--drive-use-trash=false"])
        self.clock = clock
        self._cache: dict[str, tuple[float, list[dict]]] = {}

    @property
    def configured(self) -> bool:
        return bool(self.remote)

    def _base(self) -> list[str]:
        return [self.rclone] + (["--config", self.config] if self.config else [])

    async def _run(self, args: list[str], timeout: float = 120) -> bytes:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._base(), *args, *self.extra,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except FileNotFoundError as exc:
            raise CloudError("rclone_missing") from exc
        except asyncio.TimeoutError as exc:
            raise CloudError("cloud_timeout") from exc
        if proc.returncode != 0:
            msg = err.decode(errors="replace").strip()[-200:]
            log.warning("rclone %s failed: %s", args[0], msg)
            if "directory not found" in msg.lower():
                raise CloudError("not_found")
            raise CloudError("cloud_error")
        return out

    # ------------------------------------------------------------ listing
    async def folders(self) -> list[str]:
        out = await self._run(["lsjson", "--dirs-only", self.remote])
        return sorted(e["Name"] for e in json.loads(out or b"[]") if FOLDER_RE.match(e.get("Name", "")))

    async def files(self, folder: str, fresh: bool = False) -> list[dict]:
        if not FOLDER_RE.match(folder):
            raise CloudError("bad_folder")
        hit = self._cache.get(folder)
        if hit and not fresh and self.clock() - hit[0] < CACHE_S:
            return hit[1]
        out = await self._run(["lsjson", "--files-only", f"{self.remote}/{folder}"])
        files = [
            {"name": e["Name"], "size": int(e.get("Size", 0)), "kind": clip_kind(e["Name"])}
            for e in json.loads(out or b"[]") if FILE_RE.match(e.get("Name", "")) and clip_kind(e["Name"])
        ]
        files.sort(key=lambda f: f["name"])
        self._cache[folder] = (self.clock(), files)
        return files

    async def size(self) -> dict:
        out = await self._run(["size", "--json", self.remote], timeout=300)
        data = json.loads(out or b"{}")
        return {"count": int(data.get("count", 0)), "bytes": int(data.get("bytes", 0)), "at": self.clock()}

    # ------------------------------------------------------------ deleting
    async def purge(self, folder: str) -> None:
        if not FOLDER_RE.match(folder):                       # never anything that is not an event folder
            raise CloudError("bad_folder")
        await self._run(["purge", f"{self.remote}/{folder}", *self.purge_args], timeout=300)
        self._cache.pop(folder, None)

    # ------------------------------------------------------------ streaming
    async def stream(self, folder: str, name: str, offset: int, count: int | None) -> AsyncIterator[bytes]:
        if not FOLDER_RE.match(folder) or not FILE_RE.match(name):
            raise CloudError("bad_name")
        args = [*self._base(), "cat", f"{self.remote}/{folder}/{name}", "--offset", str(offset), *self.extra]
        if count is not None:
            args += ["--count", str(count)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=2 ** 20)
        except FileNotFoundError as exc:
            raise CloudError("rclone_missing") from exc
        try:
            while True:
                chunk = await proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            if proc.returncode is None:                       # the phone stopped watching: stop downloading
                proc.kill()
            await proc.wait()
