"""Pure schedule maths: when is the system supposed to be watching?

No I/O and no clock of its own; everything takes an explicit `now` (epoch seconds)
and a tzinfo, so it is easy to test (including overnight windows and DST).

A window is {"days": [0..6] (Mon=0), "start": "HH:MM", "end": "HH:MM"}.
If end <= start the window runs past midnight into the next day (22:00-07:00).
A window "belongs" to the day it starts on.

A day can be skipped (a day you are at home): by calendar date (skip_dates) or by
weekday (home_weekdays, e.g. every Wednesday you work from home). A skipped day
cancels every window that STARTS on that day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo


def parse_hhmm(text: str) -> time:
    h, m = str(text).split(":")
    h, m = int(h), int(m)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"bad time {text!r}")
    return time(h, m)


def minutes_of(text: str) -> int:
    t = parse_hhmm(text)
    return t.hour * 60 + t.minute


def in_daily_range(now: float, tz: tzinfo, start: str, end: str) -> bool:
    """True if local time-of-day is inside [start, end). Wraps past midnight; start == end means never."""
    local = datetime.fromtimestamp(now, tz)
    cur = local.hour * 60 + local.minute
    a, b = minutes_of(start), minutes_of(end)
    if a == b:
        return False
    if a < b:
        return a <= cur < b
    return cur >= a or cur < b


@dataclass(frozen=True)
class Span:
    start: float
    end: float
    day: str           # ISO date the span starts on
    skipped: str | None = None   # None | "date" | "weekday"


def _at(d: date, t: time, tz: tzinfo) -> datetime:
    return datetime.combine(d, t, tzinfo=tz)


def spans(sched: dict, now: float, tz: tzinfo, back_days: int = 2, ahead_days: int = 9) -> list[Span]:
    """All window instances around `now`, each flagged with why it is skipped (if it is)."""
    today = datetime.fromtimestamp(now, tz).date()
    skip_dates = set(sched.get("skip_dates", []))
    home = set(sched.get("home_weekdays", []))
    out: list[Span] = []
    for offset in range(-back_days, ahead_days + 1):
        d = today + timedelta(days=offset)
        for w in sched.get("windows", []):
            if d.weekday() not in w["days"]:
                continue
            a, b = parse_hhmm(w["start"]), parse_hhmm(w["end"])
            start = _at(d, a, tz)
            end = _at(d if b > a else d + timedelta(days=1), b, tz)
            why = "date" if d.isoformat() in skip_dates else "weekday" if d.weekday() in home else None
            out.append(Span(start.timestamp(), end.timestamp(), d.isoformat(), why))
    out.sort(key=lambda s: s.start)
    return out


def _merge(items: list[Span]) -> list[Span]:
    """Join overlapping or touching spans so 23:00-07:00 + 07:00-08:30 never flaps at 07:00."""
    merged: list[Span] = []
    for s in items:
        if merged and s.start <= merged[-1].end:
            last = merged[-1]
            merged[-1] = Span(last.start, max(last.end, s.end), last.day)
        else:
            merged.append(s)
    return merged


def evaluate(sched: dict, now: float, tz: tzinfo) -> dict:
    """Where are we relative to the schedule?

    Returns:
        active          the schedule wants the system armed right now
        window_start / window_end     the current merged window (or None)
        next_start      start of the next window that will actually run (or None)
        next_end        end of the next window
        skipped_now     None, or "date"/"weekday" when today's window was cancelled
        skipped_next    {"day": iso, "why": ...} for the next cancelled window, if any
    """
    all_spans = spans(sched, now, tz)
    live = _merge([s for s in all_spans if s.skipped is None])
    cur = next((s for s in live if s.start <= now < s.end), None)
    nxt = next((s for s in live if s.start > now), None)
    skipped_now = next((s.skipped for s in all_spans if s.skipped and s.start <= now < s.end), None)
    skipped_next = next(
        ({"day": s.day, "why": s.skipped} for s in all_spans if s.skipped and s.start > now), None
    )
    return {
        "active": cur is not None,
        "window_start": cur.start if cur else None,
        "window_end": cur.end if cur else None,
        "next_start": nxt.start if nxt else None,
        "next_end": nxt.end if nxt else None,
        "skipped_now": skipped_now if cur is None else None,
        "skipped_next": skipped_next,
    }
