"""Config loading: YAML file merged over built-in defaults."""

from __future__ import annotations

import copy
from datetime import datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

DEFAULTS: dict = {
    "api": {"host": "0.0.0.0", "port": 8088, "token": ""},
    "paths": {"data_dir": "/var/lib/sentinel", "ring_dir": "/dev/shm/sentinel"},
    "mqtt": {"host": "127.0.0.1", "port": 1883, "username": "", "password": "", "base_topic": "zigbee2mqtt"},
    "sensors": [],
    "siren": {
        "enabled": True,
        "z2m": "siren",
        "type": "siren_on",       # "siren_on" (Sonoff SNZB-09P) or "warning" (Heiman/Neo/most others)
        "duration_s": 120,
        "test_s": 3,
        "settings": {
            "alarm_sound_enable": "ON",       # Zigbee2MQTT wants "ON"/"OFF" here: a true/false value switches it OFF
            "alarm_light_enable": "ON",
            "alarm_volume_level": "max",
        },
    },
    "timing": {},
    "camera": {
        "ffmpeg": "ffmpeg",
        "rtsp_main": "",
        "rtsp_sub": "",
        "segment_s": 10,
        "preroll_s": 30,
        "input_args": None,
        # Pan/tilt from the app. Address, user and password come from rtsp_main by default.
        "ptz": {"enabled": True, "speed": "normal", "arm_preset": 0},
    },
    "cloud": {
        "remote": "",             # e.g. "gdrive:SecurityCam" ; empty = keep clips on the SD card only
        "rclone": "rclone",
        "rclone_config": "",
        "chunk_s": 60,
        "extra_args": [],
        "cleanup_at": "03:30",    # when the nightly clean-up of old recordings runs (local time)
        "purge_args": ["--drive-use-trash=false"],   # Drive: really delete, don't just move to the trash (which still counts as used space)
    },
    "push": {"enabled": True},
    "healthchecks_url": "",
    "timezone": "",               # e.g. "Europe/Paris". Empty = the Pi's own time zone.
    "live": {"hls_url": "http://{host}:1984/api/stream.m3u8?src=room_sub&mp4"},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def validate(cfg: dict) -> None:
    token = cfg["api"].get("token", "")
    if not token or token == "CHANGE_ME":
        raise ValueError("api.token must be set to a long random string")
    if not cfg["sensors"]:
        raise ValueError("define at least one sensor under 'sensors'")
    try:
        timezone(cfg)
    except Exception:
        raise ValueError(f"unknown timezone {cfg.get('timezone')!r} (use a name like Europe/Paris)") from None
    ptz = cfg["camera"].get("ptz") or {}
    if ptz.get("speed", "normal") not in ("slow", "normal", "fast"):
        raise ValueError("camera.ptz.speed must be slow, normal or fast")
    arm_preset = ptz.get("arm_preset", 0) or 0
    if isinstance(arm_preset, bool) or not isinstance(arm_preset, int) or not 0 <= arm_preset <= 64:
        raise ValueError("camera.ptz.arm_preset must be 0 (off) or a preset number from 1 to 64")
    names = set()
    for s in cfg["sensors"]:
        for key in ("name", "z2m", "kind"):
            if key not in s:
                raise ValueError(f"sensor missing '{key}': {s}")
        if s["kind"] not in ("contact", "motion"):
            raise ValueError(f"sensor kind must be contact or motion: {s}")
        if s["name"] in names:
            raise ValueError(f"duplicate sensor name {s['name']}")
        names.add(s["name"])


def timezone(cfg: dict) -> tzinfo:
    name = cfg.get("timezone") or ""
    return ZoneInfo(name) if name else datetime.now().astimezone().tzinfo


def load(path: str | Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cfg = _merge(DEFAULTS, data)
    validate(cfg)
    return cfg
