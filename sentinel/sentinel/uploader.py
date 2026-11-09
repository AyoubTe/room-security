"""Uploads finished clips from the spool folder to the cloud with rclone.

The spool is just a directory: <spool>/<event-folder>/<file>. Anything in
there (except *.tmp files still being written) is uploaded, then deleted.
Because the queue *is* the directory, it survives restarts and internet
outages with no extra bookkeeping.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

log = logging.getLogger("sentinel.uploader")


class Uploader:
    def __init__(self, cfg: dict, spool: Path, on_failing=None, on_recovered=None):
        cloud = cfg["cloud"]
        self.remote = cloud["remote"].rstrip("/")
        self.rclone = cloud["rclone"]
        self.rclone_config = cloud.get("rclone_config") or ""
        self.extra = list(cloud.get("extra_args") or [])
        self.spool = spool
        self.on_failing = on_failing
        self.on_recovered = on_recovered
        self.fail_count = 0
        self.last_ok: float | None = None
        self.last_error: str | None = None
        self._delay = 10.0
        self._kick = asyncio.Event()
        self._stop = False

    @property
    def configured(self) -> bool:
        return bool(self.remote)

    def kick(self) -> None:
        self._kick.set()

    def stop(self) -> None:
        self._stop = True
        self._kick.set()

    def pending(self) -> list[Path]:
        if not self.spool.exists():
            return []
        files = [p for p in self.spool.glob("*/*") if p.is_file() and p.suffix != ".tmp"]
        return sorted(files, key=lambda p: (p.stat().st_mtime, p.name))

    def status(self) -> dict:
        files = self.pending()
        return {
            "configured": self.configured,
            "pending_files": len(files),
            "pending_mb": round(sum(p.stat().st_size for p in files) / 1e6, 1),
            "last_ok": self.last_ok,
            "last_error": self.last_error,
        }

    def _cmd(self, path: Path) -> list[str]:
        cmd = [self.rclone]
        if self.rclone_config:
            cmd += ["--config", self.rclone_config]
        cmd += [
            "copyto", str(path), f"{self.remote}/{path.parent.name}/{path.name}",
            "--retries", "2", "--low-level-retries", "5",
            "--contimeout", "20s", "--timeout", "90s", *self.extra,
        ]
        return cmd

    async def _upload(self, path: Path) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._cmd(path), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            _, err = await proc.communicate()
        except FileNotFoundError:
            self.last_error = f"rclone not found: {self.rclone}"
            return False
        if proc.returncode == 0:
            return True
        self.last_error = err.decode(errors="replace").strip()[-300:] or f"rclone exit {proc.returncode}"
        return False

    async def run_once(self) -> bool:
        """Upload everything pending. Returns False if a file failed (caller backs off)."""
        if not self.configured:
            return True
        for path in self.pending():
            if await self._upload(path):
                size = path.stat().st_size
                path.unlink(missing_ok=True)
                try:
                    path.parent.rmdir()          # only succeeds when the folder is empty
                except OSError:
                    pass
                self.last_ok = time.time()
                self.last_error = None
                log.info("uploaded %s (%.1f MB)", path.name, size / 1e6)
                if self.fail_count >= 3 and self.on_recovered:
                    self.on_recovered()
                self.fail_count = 0
                self._delay = 10.0
            else:
                self.fail_count += 1
                log.warning("upload failed (%d): %s", self.fail_count, self.last_error)
                if self.fail_count == 5 and self.on_failing:
                    self.on_failing(self.last_error)
                return False
        return True

    async def run(self) -> None:
        while not self._stop:
            ok = await self.run_once()
            self._delay = 10.0 if ok else min(300.0, self._delay * 2)
            try:
                await asyncio.wait_for(self._kick.wait(), timeout=self._delay)
            except asyncio.TimeoutError:
                pass
            self._kick.clear()
