/**
 * JS port of the Pi's schedule maths (sentinel/schedule.py), used only by the demo so the
 * "next arms at" lines behave like the real thing. The real app asks the Pi instead.
 */

const pad = n => String(n).padStart(2, '0');

function offsetMs(epochMs, tz) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).formatToParts(new Date(epochMs)).map(p => [p.type, p.value])
  );
  const asUtc = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute, +parts.second);
  return asUtc - Math.floor(epochMs / 1000) * 1000;
}

/** Local wall-clock time in `tz` -> epoch seconds. */
export function zonedEpoch(y, m, d, hh, mm, tz) {
  const guess = Date.UTC(y, m - 1, d, hh, mm);
  const first = guess - offsetMs(guess, tz);
  return (guess - offsetMs(first, tz)) / 1000;
}

export function localDate(epochS, tz) {
  return new Date(epochS * 1000).toLocaleDateString('en-CA', { timeZone: tz });
}

const hm = s => s.split(':').map(Number);

export function spans(sched, nowS, tz) {
  const [y, m, d] = localDate(nowS, tz).split('-').map(Number);
  const out = [];
  for (let off = -2; off <= 9; off += 1) {
    const day = new Date(Date.UTC(y, m - 1, d + off));
    const wd = (day.getUTCDay() + 6) % 7;
    const iso = `${day.getUTCFullYear()}-${pad(day.getUTCMonth() + 1)}-${pad(day.getUTCDate())}`;
    sched.windows.forEach(w => {
      if (!w.days.includes(wd)) return;
      const [ah, am] = hm(w.start);
      const [bh, bm] = hm(w.end);
      const overnight = bh * 60 + bm <= ah * 60 + am;
      const start = zonedEpoch(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate(), ah, am, tz);
      const endDay = overnight ? new Date(Date.UTC(y, m - 1, d + off + 1)) : day;
      const end = zonedEpoch(endDay.getUTCFullYear(), endDay.getUTCMonth() + 1, endDay.getUTCDate(), bh, bm, tz);
      const skipped = sched.skip_dates.includes(iso) ? 'date' : sched.home_weekdays.includes(wd) ? 'weekday' : null;
      out.push({ start, end, day: iso, skipped });
    });
  }
  return out.sort((a, b) => a.start - b.start);
}

export function evaluate(sched, nowS, tz) {
  const all = spans(sched, nowS, tz);
  const merged = [];
  all.filter(s => !s.skipped).forEach(s => {
    const last = merged[merged.length - 1];
    if (last && s.start <= last.end) last.end = Math.max(last.end, s.end);
    else merged.push({ ...s });
  });
  const cur = merged.find(s => s.start <= nowS && nowS < s.end) || null;
  const next = merged.find(s => s.start > nowS) || null;
  const skippedNow = all.find(s => s.skipped && s.start <= nowS && nowS < s.end);
  const skippedNext = all.find(s => s.skipped && s.start > nowS);
  return {
    active: !!cur,
    window_start: cur?.start ?? null,
    window_end: cur?.end ?? null,
    next_start: next?.start ?? null,
    next_end: next?.end ?? null,
    skipped_now: cur ? null : skippedNow?.skipped ?? null,
    skipped_next: skippedNext ? { day: skippedNext.day, why: skippedNext.skipped } : null,
  };
}
