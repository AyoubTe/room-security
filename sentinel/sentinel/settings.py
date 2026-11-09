"""Settings the app can change at runtime (schedule, siren policy, delays, sensor bypass).

They live in SQLite (kv "settings"), so a restart keeps them; config.yaml only holds the
installation-time values and acts as the fallback. Validation is strict: the app never
gets to store something the scheduler can't understand.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime, tzinfo

from .schedule import parse_hhmm

VOLUMES = ("low", "medium", "high", "max")
SIREN_MODES = ("on", "silent", "quiet_hours")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULTS: dict = {
    "schedule": {
        "enabled": False,
        "windows": [],              # [{"days": [0,1,2,3,4], "start": "08:30", "end": "18:00"}]
        "home_weekdays": [],        # weekdays you usually work from home (0=Mon ... 6=Sun)
        "skip_dates": [],           # one-off days at home, "YYYY-MM-DD"
        "paused_until": None,       # epoch: schedule does nothing until then
        "auto_disarm": True,        # disarm when a window ends (only if the schedule armed it)
        "smart_arm": True,          # postpone auto-arm while you are moving in the room
        "busy_s": 300,              # "moving in the room" = motion in the last N seconds
        "pre_arm_warning_min": 10,  # push N minutes before auto-arm (0 = off)
        # Away for a while: armed round the clock, ignoring windows, days at home and pauses.
        "vacation": {"active": False, "since": None, "until": None},   # until: epoch, None = until switched off
    },
    # Which saved camera view to turn to when a sensor triggers: {"door": 3, "window": 2, "motion": 1}
    "camera": {"follow": True, "views": {}, "return_view": None, "return_after_s": 120},
    # Recordings and alerts older than this are deleted every night (0 = keep everything). Paused on vacation.
    "cloud": {"retention_days": 15},
    "siren": {
        "mode": "on",               # on | silent | quiet_hours
        "quiet_hours": {"start": "22:00", "end": "07:00"},
        "volume": "max",
        "duration_s": None,         # None = value from config.yaml
    },
    "timing": {"exit_delay_s": None, "entry_delay_s": None},   # None = config.yaml
    # per sensor: {"enabled": bool, "until": epoch|None, "until_closed": bool, "saw_open": bool}
    "sensors": {},
}


def sensor_default() -> dict:
    return {"enabled": True, "until": None, "until_closed": False, "saw_open": False}


def defaults(sensor_names: list[str]) -> dict:
    d = copy.deepcopy(DEFAULTS)
    d["sensors"] = {n: sensor_default() for n in sensor_names}
    return d


def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _bool(v, name):
    if not isinstance(v, bool):
        raise ValueError(f"{name} must be true or false")
    return v


def _int(v, name, lo, hi, allow_none=False):
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
        raise ValueError(f"{name} must be a whole number")
    if not lo <= v <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return int(v)


def _hhmm(v, name):
    try:
        parse_hhmm(v)
    except Exception:
        raise ValueError(f"{name} must look like 08:30") from None
    h, m = str(v).split(":")
    return f"{int(h):02d}:{int(m):02d}"


def validate(s: dict, sensor_names: list[str], tz: tzinfo, now: float) -> dict:
    """Returns a cleaned copy of `s` or raises ValueError with a message the app can show."""
    out = defaults(sensor_names)

    sc = s.get("schedule", {})
    o = out["schedule"]
    o["enabled"] = _bool(sc.get("enabled", False), "schedule.enabled")
    o["auto_disarm"] = _bool(sc.get("auto_disarm", True), "schedule.auto_disarm")
    o["smart_arm"] = _bool(sc.get("smart_arm", True), "schedule.smart_arm")
    o["busy_s"] = _int(sc.get("busy_s", 300), "schedule.busy_s", 30, 3600)
    o["pre_arm_warning_min"] = _int(sc.get("pre_arm_warning_min", 10), "schedule.pre_arm_warning_min", 0, 120)

    windows = sc.get("windows", [])
    if not isinstance(windows, list) or len(windows) > 14:
        raise ValueError("schedule.windows must be a list of at most 14 windows")
    for i, w in enumerate(windows):
        if not isinstance(w, dict):
            raise ValueError(f"window {i + 1} is not valid")
        days = w.get("days")
        if (not isinstance(days, list) or not days
                or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in days)):
            raise ValueError(f"window {i + 1}: pick at least one day")
        start, end = _hhmm(w.get("start"), f"window {i + 1} start"), _hhmm(w.get("end"), f"window {i + 1} end")
        o["windows"].append({"days": sorted(set(days)), "start": start, "end": end})

    home = sc.get("home_weekdays", [])
    if (not isinstance(home, list)
            or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in home)):
        raise ValueError("schedule.home_weekdays must be weekday numbers 0-6")
    o["home_weekdays"] = sorted(set(home))

    today = datetime.fromtimestamp(now, tz).date()
    dates = sc.get("skip_dates", [])
    if not isinstance(dates, list) or len(dates) > 400:
        raise ValueError("schedule.skip_dates must be a list of dates")
    keep = set()
    for d in dates:
        if not isinstance(d, str) or not DATE_RE.match(d):
            raise ValueError(f"bad date {d!r}, use YYYY-MM-DD")
        try:
            parsed = date.fromisoformat(d)
        except ValueError:
            raise ValueError(f"bad date {d!r}") from None
        if (today - parsed).days <= 1:        # forget old days so the list never grows forever
            keep.add(d)
    o["skip_dates"] = sorted(keep)

    va = sc.get("vacation") or {}
    active = _bool(va.get("active", False), "vacation.active")
    until, since = va.get("until"), va.get("since")
    for label, v in (("until", until), ("since", since)):
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
            raise ValueError(f"vacation.{label} must be a timestamp or null")
    if active and until is not None and until <= now:        # the trip is over
        active, until, since = False, None, None
    o["vacation"] = {
        "active": active,
        "since": float(since) if active and since else None,
        "until": float(until) if active and until else None,
    }

    pu = sc.get("paused_until")
    if pu is not None and (isinstance(pu, bool) or not isinstance(pu, (int, float))):
        raise ValueError("schedule.paused_until must be a timestamp or null")
    o["paused_until"] = float(pu) if pu and pu > now else None

    si = s.get("siren", {})
    mode = si.get("mode", "on")
    if mode not in SIREN_MODES:
        raise ValueError(f"siren.mode must be one of {', '.join(SIREN_MODES)}")
    out["siren"]["mode"] = mode
    q = si.get("quiet_hours", {})
    out["siren"]["quiet_hours"] = {
        "start": _hhmm(q.get("start", "22:00"), "quiet hours start"),
        "end": _hhmm(q.get("end", "07:00"), "quiet hours end"),
    }
    if mode == "quiet_hours" and out["siren"]["quiet_hours"]["start"] == out["siren"]["quiet_hours"]["end"]:
        raise ValueError("quiet hours start and end must differ")
    vol = si.get("volume", "max")
    if vol not in VOLUMES:
        raise ValueError(f"siren.volume must be one of {', '.join(VOLUMES)}")
    out["siren"]["volume"] = vol
    out["siren"]["duration_s"] = _int(si.get("duration_s"), "siren.duration_s", 5, 600, allow_none=True)

    ca = s.get("camera", {})
    out["camera"]["follow"] = _bool(ca.get("follow", True), "camera.follow")
    views = ca.get("views", {})
    if not isinstance(views, dict):
        raise ValueError("camera.views must map sensors to saved views")
    unknown_views = set(views) - set(sensor_names)
    if unknown_views:
        raise ValueError(f"unknown sensor in camera.views: {', '.join(sorted(unknown_views))}")
    for name, pid in views.items():
        pid = _int(pid, f"saved view for {name}", 0, 64, allow_none=True)
        if pid is not None:
            out["camera"]["views"][name] = pid

    # After the intrusion ends, turn back to this saved view (None = stay where it is) once it has been quiet this long.
    out["camera"]["return_view"] = _int(ca.get("return_view"), "camera return view", 0, 64, allow_none=True)
    out["camera"]["return_after_s"] = _int(ca.get("return_after_s", 120), "camera return delay", 30, 1800)

    out["cloud"]["retention_days"] = _int(s.get("cloud", {}).get("retention_days", 15), "retention days", 0, 365)

    ti = s.get("timing", {})
    out["timing"]["exit_delay_s"] = _int(ti.get("exit_delay_s"), "exit delay", 5, 300, allow_none=True)
    out["timing"]["entry_delay_s"] = _int(ti.get("entry_delay_s"), "entry delay", 5, 300, allow_none=True)

    se = s.get("sensors", {})
    for name in sensor_names:
        z = {**sensor_default(), **(se.get(name) or {})}
        z["enabled"] = _bool(z["enabled"], f"{name}.enabled")
        z["until_closed"] = _bool(z["until_closed"], f"{name}.until_closed")
        z["saw_open"] = _bool(z["saw_open"], f"{name}.saw_open")
        u = z["until"]
        if u is not None and (isinstance(u, bool) or not isinstance(u, (int, float))):
            raise ValueError(f"{name}.until must be a timestamp or null")
        z["until"] = float(u) if u else None
        if z["enabled"]:                      # a sensor that is on carries no leftovers
            z.update(until=None, until_closed=False, saw_open=False)
        out["sensors"][name] = z
    unknown = set(se) - set(sensor_names)
    if unknown:
        raise ValueError(f"unknown sensor: {', '.join(sorted(unknown))}")
    return out


def load(raw: str | None, sensor_names: list[str], tz: tzinfo, now: float) -> dict:
    if raw:
        try:
            return validate(json.loads(raw), sensor_names, tz, now)
        except Exception:
            pass                               # corrupt or from an older layout: fall back to defaults
    return defaults(sensor_names)


def apply_patch(current: dict, patch: dict, sensor_names: list[str], tz: tzinfo, now: float) -> dict:
    """Deep-merge `patch` over `current` (lists are replaced, not merged) and validate the result."""
    if not isinstance(patch, dict):
        raise ValueError("settings must be an object")
    unknown = set(patch) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown setting: {', '.join(sorted(unknown))}")
    return validate(_merge(current, patch), sensor_names, tz, now)


def siren_silent(s: dict, now: float, tz: tzinfo) -> bool:
    from .schedule import in_daily_range

    mode = s["siren"]["mode"]
    if mode == "silent":
        return True
    if mode == "quiet_hours":
        q = s["siren"]["quiet_hours"]
        return in_daily_range(now, tz, q["start"], q["end"])
    return False
