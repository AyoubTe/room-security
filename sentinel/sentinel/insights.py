"""Numbers for the app's Insights screen, computed from the event log (pure, no I/O).

Everything is derived from what the service already logs, so there is no separate
statistics store to keep in sync: alarms and triggers per day, when during the day
things happen, how long the room was armed, and which sensor fires most.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, tzinfo

ARM_START = ("arming", "restored")


def _day_bounds(today, tz: tzinfo, back: int) -> tuple[float, float]:
    d = today - timedelta(days=back)
    start = datetime.combine(d, time(0), tzinfo=tz).timestamp()
    end = datetime.combine(d + timedelta(days=1), time(0), tzinfo=tz).timestamp()
    return start, end


def build(rows: list[dict], now: float, tz: tzinfo, days: int, armed_now: bool) -> dict:
    """`rows`: log rows oldest first (see Store.since)."""
    today = datetime.fromtimestamp(now, tz).date()
    bounds = [_day_bounds(today, tz, days - 1 - i) for i in range(days)]
    out_days = [
        {"date": (today - timedelta(days=days - 1 - i)).isoformat(), "alarms": 0, "triggers": 0, "armed_s": 0}
        for i in range(days)
    ]
    first, last = bounds[0][0], bounds[-1][1]

    hours = [0] * 24
    by_sensor: dict[str, int] = {}
    totals = {"alarms": 0, "triggers": 0, "clips": 0}
    last_alarm = None
    intervals: list[tuple[float, float]] = []
    armed_since: float | None = None

    for r in rows:
        ts, kind = r["ts"], r["kind"]
        if kind in ARM_START and armed_since is None:
            armed_since = ts
        elif kind == "disarmed" and armed_since is not None:
            intervals.append((armed_since, ts))
            armed_since = None

        if not first <= ts < last:
            continue
        idx = next(i for i, (a, b) in enumerate(bounds) if a <= ts < b)
        if kind == "alarm":
            out_days[idx]["alarms"] += 1
            totals["alarms"] += 1
            last_alarm = {"ts": ts, "text": r["text"]}
        elif kind == "trigger":
            out_days[idx]["triggers"] += 1
            totals["triggers"] += 1
            name = (r.get("data") or {}).get("sensor")
            if name:
                by_sensor[name] = by_sensor.get(name, 0) + 1
        elif kind == "clips":
            totals["clips"] += (r.get("data") or {}).get("parts", 0) or 0
        if kind in ("alarm", "trigger"):
            hours[datetime.fromtimestamp(ts, tz).hour] += 1

    if armed_now and armed_since is not None:
        intervals.append((armed_since, now))

    for a, b in intervals:
        for i, (ds, de) in enumerate(bounds):
            overlap = min(b, de, now) - max(a, ds)
            if overlap > 0:
                out_days[i]["armed_s"] += int(overlap)

    elapsed = max(1.0, min(now, last) - first)
    armed_total = sum(d["armed_s"] for d in out_days)
    return {
        "days": out_days,
        "hours": hours,
        "by_sensor": [{"sensor": k, "count": v} for k, v in sorted(by_sensor.items(), key=lambda kv: -kv[1])],
        "totals": {**totals, "armed_s": armed_total, "armed_pct": round(100 * armed_total / elapsed, 1)},
        "last_alarm": last_alarm,
    }
