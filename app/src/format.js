/** Time helpers. Schedules run in the Pi's time zone, so everything is shown in that zone, not the phone's. */

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
export const DAY_LETTERS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

function safe(fn, fallback) {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

export function fmtClock(ts, tz) {
  if (ts == null) return '—';
  const d = new Date(ts * 1000);
  return safe(
    () => d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: tz || undefined }),
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  );
}

/** "Thu 08:30", or just "08:30" when it is today in the Pi's zone. */
export function fmtDayTime(ts, tz, nowTs) {
  if (ts == null) return '—';
  const d = new Date(ts * 1000);
  const dayKey = x => safe(() => x.toLocaleDateString('en-CA', { timeZone: tz || undefined }), x.toDateString());
  const same = dayKey(d) === dayKey(new Date((nowTs ?? Date.now() / 1000) * 1000));
  if (same) return fmtClock(ts, tz);
  const wd = safe(() => d.toLocaleDateString('en-GB', { weekday: 'short', timeZone: tz || undefined }), '');
  return `${wd} ${fmtClock(ts, tz)}`.trim();
}

/** "Sun 22 Nov": a date with its weekday, for things that are days away. */
export function fmtDateShort(ts, tz) {
  if (ts == null) return '—';
  const d = new Date(ts * 1000);
  return safe(() => d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: tz || undefined }).replace(',', ''), d.toDateString());
}

export function fmtLeft(seconds) {
  const m = Math.max(1, Math.round(seconds / 60));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

/** The next `count` calendar days in the Pi's zone: [{ iso, wd (0=Mon), label, num }]. */
export function piDays(tz, count = 14, nowTs = Date.now() / 1000) {
  const today = safe(
    () => new Date(nowTs * 1000).toLocaleDateString('en-CA', { timeZone: tz || undefined }),
    new Date(nowTs * 1000).toISOString().slice(0, 10)
  );
  const [y, m, d] = today.split('-').map(Number);
  const out = [];
  for (let i = 0; i < count; i += 1) {
    const dt = new Date(Date.UTC(y, m - 1, d + i));
    const wd = (dt.getUTCDay() + 6) % 7;
    out.push({ iso: dt.toISOString().slice(0, 10), wd, label: WEEKDAYS[wd], num: dt.getUTCDate() });
  }
  return out;
}

/** "8", "830", "8:30", "0830" -> "08:30"; anything else -> null. */
export function parseTime(text) {
  const m = String(text).trim().match(/^(\d{1,2}):?(\d{2})?$/);
  if (!m) return null;
  const h = Number(m[1]);
  const min = m[2] == null ? 0 : Number(m[2]);
  if (h > 23 || min > 59) return null;
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}

export function shiftTime(text, minutes) {
  const [h, m] = text.split(':').map(Number);
  const total = (((h * 60 + m + minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

export function greeting(date = new Date()) {
  const h = date.getHours();
  if (h < 5) return 'Good night';
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

/** 2h 05m style from seconds. */
export function fmtHours(seconds) {
  const m = Math.round(seconds / 60);
  const h = Math.floor(m / 60);
  const r = m % 60;
  if (h === 0) return `${r}m`;
  return `${h}h ${String(r).padStart(2, '0')}m`;
}

export function fmtAgo(ts, nowTs) {
  const s = Math.max(0, Math.round((nowTs ?? Date.now() / 1000) - ts));
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function fmtUptime(seconds) {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  if (d > 0) return `${d}d ${h}h`;
  return `${h}h ${Math.floor((seconds % 3600) / 60)}m`;
}

/** Heading for a day group in the timeline: Today, Yesterday, or "Mon 2 Nov". */
export function dayLabel(ts, tz, nowTs = Date.now() / 1000) {
  const key = t => safe(() => new Date(t * 1000).toLocaleDateString('en-CA', { timeZone: tz || undefined }), '');
  if (key(ts) === key(nowTs)) return 'Today';
  if (key(ts) === key(nowTs - 86400)) return 'Yesterday';
  return safe(
    () => new Date(ts * 1000).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: tz || undefined }),
    new Date(ts * 1000).toDateString()
  );
}

export function dayKey(ts, tz) {
  return safe(() => new Date(ts * 1000).toLocaleDateString('en-CA', { timeZone: tz || undefined }), String(Math.floor(ts / 86400)));
}

export function fmtDate(isoDate) {
  const [y, m, d] = isoDate.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
}
