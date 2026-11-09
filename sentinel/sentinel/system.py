"""Health of the Raspberry Pi itself, for the app's Devices screen. Every value may be None
(for example on a machine without /sys/class/thermal); nothing here raises."""

from __future__ import annotations

import os
import shutil


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def snapshot(data_dir: str) -> dict:
    temp = _read("/sys/class/thermal/thermal_zone0/temp")
    try:
        cpu_temp = round(int(temp.strip()) / 1000, 1) if temp else None
    except ValueError:
        cpu_temp = None

    try:
        load1 = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        load1 = None

    mem_pct = None
    meminfo = _read("/proc/meminfo")
    if meminfo:
        try:
            vals = {k: int(v.split()[0]) for k, v in (ln.split(":", 1) for ln in meminfo.splitlines() if ":" in ln)}
            mem_pct = round(100 * (1 - vals["MemAvailable"] / vals["MemTotal"]), 1)
        except (KeyError, ValueError, ZeroDivisionError):
            mem_pct = None

    disk_pct = disk_free_gb = None
    try:
        du = shutil.disk_usage(data_dir)
        disk_pct = round(100 * du.used / du.total, 1)
        disk_free_gb = round(du.free / 1e9, 1)
    except OSError:
        pass

    up = _read("/proc/uptime")
    try:
        host_uptime = int(float(up.split()[0])) if up else None
    except (ValueError, IndexError):
        host_uptime = None

    return {
        "cpu_temp_c": cpu_temp, "load1": load1, "mem_used_pct": mem_pct,
        "disk_used_pct": disk_pct, "disk_free_gb": disk_free_gb, "host_uptime_s": host_uptime,
    }
