from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sentinel import settings as cfgmod
from sentinel.schedule import evaluate, in_daily_range, spans

TZ = ZoneInfo("Europe/Paris")


def at(text):
    """'2026-11-04 08:30' (Paris) -> epoch."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=TZ).timestamp()


def sched(**kw):
    base = {"windows": [], "home_weekdays": [], "skip_dates": []}
    base.update(kw)
    return base


WORK = {"days": [0, 1, 2, 3, 4], "start": "08:30", "end": "18:00"}
NIGHT = {"days": [0, 1, 2, 3, 4, 5, 6], "start": "22:00", "end": "07:00"}
# 2026-11-04 is a Wednesday (weekday 2)


def test_simple_window():
    s = sched(windows=[WORK])
    assert not evaluate(s, at("2026-11-04 08:29"), TZ)["active"]
    ev = evaluate(s, at("2026-11-04 08:30"), TZ)
    assert ev["active"] and ev["window_end"] == at("2026-11-04 18:00")
    assert not evaluate(s, at("2026-11-04 18:00"), TZ)["active"]
    assert evaluate(s, at("2026-11-04 12:00"), TZ)["next_start"] == at("2026-11-05 08:30")


def test_weekend_has_no_work_window():
    s = sched(windows=[WORK])
    sat = evaluate(s, at("2026-11-07 12:00"), TZ)           # Saturday
    assert not sat["active"] and sat["next_start"] == at("2026-11-09 08:30")


def test_overnight_window_belongs_to_the_day_it_starts():
    s = sched(windows=[NIGHT])
    assert evaluate(s, at("2026-11-04 23:00"), TZ)["active"]
    ev = evaluate(s, at("2026-11-05 03:00"), TZ)
    assert ev["active"] and ev["window_start"] == at("2026-11-04 22:00") and ev["window_end"] == at("2026-11-05 07:00")
    assert not evaluate(s, at("2026-11-05 12:00"), TZ)["active"]


def test_skipped_date_cancels_windows_starting_that_day_only():
    s = sched(windows=[WORK, NIGHT], skip_dates=["2026-11-04"])
    ev = evaluate(s, at("2026-11-04 12:00"), TZ)
    assert not ev["active"] and ev["skipped_now"] == "date"
    assert not evaluate(s, at("2026-11-04 23:00"), TZ)["active"]          # night window of the 4th is skipped too
    assert evaluate(s, at("2026-11-04 03:00"), TZ)["active"]              # but the one that started on the 3rd runs
    assert evaluate(s, at("2026-11-05 09:00"), TZ)["active"]              # next day is normal


def test_home_weekday_is_recurring():
    s = sched(windows=[WORK], home_weekdays=[2])                          # every Wednesday at home
    assert not evaluate(s, at("2026-11-04 12:00"), TZ)["active"]
    assert not evaluate(s, at("2026-11-11 12:00"), TZ)["active"]
    assert evaluate(s, at("2026-11-05 12:00"), TZ)["active"]
    assert evaluate(s, at("2026-11-04 12:00"), TZ)["skipped_now"] == "weekday"


def test_touching_windows_merge_without_a_gap():
    s = sched(windows=[NIGHT, {"days": [0, 1, 2, 3, 4], "start": "07:00", "end": "08:30"}])
    ev = evaluate(s, at("2026-11-05 07:00"), TZ)
    assert ev["active"] and ev["window_end"] == at("2026-11-05 08:30")


def test_clock_change_night_is_ten_hours_long():
    s = sched(windows=[{"days": [5], "start": "22:00", "end": "07:00"}])  # Saturday 24 Oct -> DST ends 25 Oct
    sp = [x for x in spans(s, at("2026-10-24 12:00"), TZ) if x.day == "2026-10-24"][0]
    assert (sp.end - sp.start) / 3600 == 10


def test_daily_range_wraps_midnight():
    assert in_daily_range(at("2026-11-04 23:30"), TZ, "22:00", "07:00")
    assert in_daily_range(at("2026-11-04 06:59"), TZ, "22:00", "07:00")
    assert not in_daily_range(at("2026-11-04 07:00"), TZ, "22:00", "07:00")
    assert not in_daily_range(at("2026-11-04 12:00"), TZ, "22:00", "07:00")
    assert in_daily_range(at("2026-11-04 12:00"), TZ, "09:00", "17:00")
    assert not in_daily_range(at("2026-11-04 12:00"), TZ, "12:00", "12:00")


NAMES = ["door", "window"]
NOW = at("2026-11-04 12:00")


def check(patch, base=None):
    return cfgmod.apply_patch(base or cfgmod.defaults(NAMES), patch, NAMES, TZ, NOW)


def test_defaults_are_valid_and_off():
    d = cfgmod.defaults(NAMES)
    assert cfgmod.validate(d, NAMES, TZ, NOW) == d
    assert d["schedule"]["enabled"] is False and d["siren"]["mode"] == "on"


@pytest.mark.parametrize("patch,msg", [
    ({"schedule": {"windows": [{"days": [], "start": "08:00", "end": "09:00"}]}}, "at least one day"),
    ({"schedule": {"windows": [{"days": [7], "start": "08:00", "end": "09:00"}]}}, "at least one day"),
    ({"schedule": {"windows": [{"days": [1], "start": "25:00", "end": "09:00"}]}}, "08:30"),
    ({"schedule": {"windows": [{"days": [1], "start": "8h", "end": "09:00"}]}}, "08:30"),
    ({"schedule": {"skip_dates": ["04/11/2026"]}}, "YYYY-MM-DD"),
    ({"schedule": {"skip_dates": ["2026-02-30"]}}, "bad date"),
    ({"schedule": {"enabled": "yes"}}, "true or false"),
    ({"siren": {"mode": "loud"}}, "siren.mode"),
    ({"siren": {"volume": "ear-splitting"}}, "siren.volume"),
    ({"siren": {"mode": "quiet_hours", "quiet_hours": {"start": "22:00", "end": "22:00"}}}, "differ"),
    ({"timing": {"exit_delay_s": 1}}, "between 5 and 300"),
    ({"sensors": {"garage": {"enabled": False}}}, "unknown sensor"),
    ({"nonsense": 1}, "unknown setting"),
])
def test_validation_rejects(patch, msg):
    with pytest.raises(ValueError, match=msg):
        check(patch)


def test_patch_merges_dicts_but_replaces_lists_and_cleans_up():
    s = check({"schedule": {"enabled": True, "windows": [WORK]}})
    s = check({"schedule": {"skip_dates": ["2026-11-04", "2026-01-01"], "windows": [NIGHT]}}, s)
    assert s["schedule"]["enabled"] is True                       # untouched key survives
    assert s["schedule"]["windows"] == [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "22:00", "end": "07:00"}]
    assert s["schedule"]["skip_dates"] == ["2026-11-04"]          # old day forgotten
    s = check({"sensors": {"window": {"enabled": False, "until": NOW + 60}}}, s)
    assert s["sensors"]["window"]["enabled"] is False
    s = check({"sensors": {"window": {"enabled": True}}}, s)
    assert s["sensors"]["window"]["until"] is None                # turning it on clears leftovers


def test_time_strings_are_normalised_and_corrupt_data_falls_back():
    s = check({"schedule": {"windows": [{"days": [1, 1, 0], "start": "8:05", "end": "17:00"}]}})
    assert s["schedule"]["windows"][0] == {"days": [0, 1], "start": "08:05", "end": "17:00"}
    assert cfgmod.load("{not json", NAMES, TZ, NOW) == cfgmod.defaults(NAMES)


def test_siren_policy():
    s = cfgmod.defaults(NAMES)
    assert not cfgmod.siren_silent(s, at("2026-11-04 23:00"), TZ)
    s["siren"]["mode"] = "silent"
    assert cfgmod.siren_silent(s, at("2026-11-04 12:00"), TZ)
    s["siren"]["mode"] = "quiet_hours"
    assert cfgmod.siren_silent(s, at("2026-11-04 23:00"), TZ)
    assert not cfgmod.siren_silent(s, at("2026-11-04 12:00"), TZ)
