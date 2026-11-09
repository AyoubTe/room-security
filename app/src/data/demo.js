/**
 * Demo client: the same interface as the real one (real.js), backed by an in-memory simulation of
 * the Pi and the smoke detector. It exists so the whole app can be explored before the hardware is
 * set up. Everything here is invented, and the UI says so ("Demo mode") wherever it is shown.
 *
 * What is simulated honestly: the arming countdown, entry delay, alarm, silent mode, silencing,
 * sensor switch-off timers, the schedule (arms/disarms by itself, days at home, pause) and the
 * Insights numbers, which are computed from the same event list the timeline shows.
 */
import { evaluate, localDate, zonedEpoch } from './schedule.js';

const TZ = 'Europe/Paris';
const ROOM_IMAGE = require('../../assets/demo/room.png');
let ptzPresets = [{ id: 1, name: 'Centre' }, { id: 2, name: 'Window' }, { id: 3, name: 'Door' }];
const DEMO_CLIP = require('../../assets/demo/clip.mp4');

const SENSOR_DEFS = [
  { name: 'door', label: 'Door', kind: 'contact', entry: true, battery: 94, lq: 182 },
  { name: 'window', label: 'Window', kind: 'contact', entry: false, battery: 34, lq: 121 },
  { name: 'motion', label: 'Motion', kind: 'motion', entry: true, battery: 88, lq: 205 },
];

const DEFAULT_SETTINGS = () => ({
  schedule: {
    enabled: true,
    windows: [
      { days: [0, 1, 2, 3, 4], start: '08:30', end: '18:00' },
      { days: [0, 1, 2, 3, 4, 5, 6], start: '22:00', end: '07:00' },
    ],
    home_weekdays: [2],
    skip_dates: [],
    paused_until: null,
    auto_disarm: true,
    smart_arm: true,
    busy_s: 300,
    pre_arm_warning_min: 10,
    vacation: { active: false, since: null, until: null },
  },
  camera: { follow: true, views: { door: 3, window: 2, motion: 1 } },
  cloud: { retention_days: 15 },
  siren: { mode: 'quiet_hours', quiet_hours: { start: '22:00', end: '07:00' }, volume: 'max', duration_s: null },
  timing: { exit_delay_s: null, entry_delay_s: null },
  sensors: Object.fromEntries(SENSOR_DEFS.map(s => [s.name, { enabled: true, until: null, until_closed: false, saw_open: false }])),
});

const BASE = { exit: 15, entry: 30, siren: 120 };

const hhmm = s => s.split(':').map(Number);
const pad = n => String(n).padStart(2, '0');

function minutesOfDay(epochS) {
  const [h, m] = new Date(epochS * 1000)
    .toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: TZ })
    .split(':')
    .map(Number);
  return (h % 24) * 60 + m;
}

function inDailyRange(epochS, start, end) {
  const cur = minutesOfDay(epochS);
  const [ah, am] = hhmm(start);
  const [bh, bm] = hhmm(end);
  const a = ah * 60 + am;
  const b = bh * 60 + bm;
  if (a === b) return false;
  return a < b ? cur >= a && cur < b : cur >= a || cur < b;
}

function folderName(ts, id) {
  const d = new Date(ts * 1000);
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
      .formatToParts(d).map(p => [p.type, p.value])
  );
  return `${parts.year}-${parts.month}-${parts.day}_${parts.hour}-${parts.minute}-${parts.second}_${id}`;
}

// ------------------------------------------------------------------ history
function seedHistory(now) {
  const events = [];
  const add = (ts, kind, text, event_id = null, data = null) => {
    if (ts <= now) events.push({ ts, kind, text, event_id, data });
  };
  const [y, m, d] = localDate(now, TZ).split('-').map(Number);
  const intervals = [];

  for (let back = 14; back >= 0; back -= 1) {
    const day = new Date(Date.UTC(y, m - 1, d - back));
    const Y = day.getUTCFullYear();
    const M = day.getUTCMonth() + 1;
    const D = day.getUTCDate();
    const wd = (day.getUTCDay() + 6) % 7;
    const iso = `${Y}-${pad(M)}-${pad(D)}`;
    const at = (hh, mm, plusDay = 0) => zonedEpoch(Y, M, D + plusDay, hh, mm, TZ);

    if (wd === 2) {
      if (back > 0) add(at(7, 5), 'schedule', `${iso} marked as a day at home (schedule skipped)`);
      continue; // Wednesdays are work-from-home days: no windows start
    }
    if (wd <= 4) intervals.push({ kind: 'work', start: at(8, 30), end: at(18, 0) });
    intervals.push({ kind: 'night', start: at(22, 0), end: at(7, 0, 1) });
  }

  // regular arming / disarming by the schedule
  intervals.forEach(iv => {
    add(iv.start, 'arming', 'Auto-arming by schedule, leave within 45 s');
    add(iv.start + 45, 'armed', 'System armed');
  });

  const pick = (minBack, kind) => {
    const limit = now - minBack * 86400;
    return [...intervals].reverse().find(iv => iv.kind === kind && iv.end <= now && iv.start <= limit) || null;
  };

  const incidents = [];
  const falseAlarm = (iv, offset, sensor, label, text) => {
    if (!iv) return;
    const ts = iv.start + offset;
    const eid = `${Math.floor(ts)}-fa${incidents.length}`;
    add(ts, 'trigger', text, eid, { sensor });
    add(ts + 14, 'disarmed', 'Disarmed during entry delay (no alarm)', eid);
    add(ts + 540, 'arming', `Arming, leave within 15 s`);
    add(ts + 555, 'armed', 'System armed');
    incidents.push({ iv, ts, label });
  };
  const alarm = (iv, offset, sensor, text, { silent = false, silenced = false, parts = 4, entry = false } = {}) => {
    if (!iv) return;
    const ts = iv.start + offset;
    const eid = `${Math.floor(ts)}-al${incidents.length}`;
    const trig = ts;
    const alarmAt = entry ? ts + 30 : ts;
    add(trig, 'trigger', text, eid, { sensor });
    add(alarmAt, 'alarm', `ALARM: ${entry ? `Entry delay expired (${text})` : text}${silent ? ' (silent: siren muted)' : ''}`, eid);
    if (silenced) add(alarmAt + 26, 'siren_silenced', 'Siren silenced from the app (recording continues)', eid);
    add(alarmAt + 150, 'alarm_end', 'Activity ended, recording closed', eid);
    add(alarmAt + 165, 'clips', `${parts} clip(s) saved to cloud folder ${folderName(alarmAt, 'a1b2')}`, eid, { parts, folder: folderName(alarmAt, 'a1b2') });
    incidents.push({ iv, ts, label: text });
  };

  alarm(pick(11, 'work'), 2 * 3600 + 12 * 60, 'window', 'Window opened', { silenced: true, parts: 3 });
  alarm(pick(5, 'work'), 4 * 3600 + 35 * 60, 'motion', 'Motion: Motion', { entry: true, parts: 5 });
  alarm(pick(3, 'night'), 3600 + 20 * 60, 'window', 'Window opened', { silent: true, parts: 6 });
  falseAlarm(pick(13, 'night'), 5 * 3600 + 17 * 60, 'door', 'Door', 'Door opened');
  falseAlarm(pick(9, 'work'), 25 * 60, 'door', 'Door', 'Door opened');
  falseAlarm(pick(7, 'work'), 7 * 3600 + 5 * 60, 'door', 'Door', 'Door opened');
  falseAlarm(pick(4, 'work'), 9 * 3600 + 2 * 60, 'motion', 'Motion', 'Motion: Motion');
  falseAlarm(pick(2, 'night'), 20 * 60, 'door', 'Door', 'Door opened');

  // housekeeping events
  const dayAgo = (n, hh, mm) => {
    const dt = new Date(Date.UTC(y, m - 1, d - n));
    return zonedEpoch(dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate(), hh, mm, TZ);
  };
  add(dayAgo(12, 11, 30), 'battery', 'Window battery 19%');
  add(dayAgo(10, 15, 2), 'sensor_offline', 'Motion offline');
  add(dayAgo(10, 15, 9), 'sensor_online', 'Motion online');
  add(dayAgo(6, 19, 40), 'settings', 'Settings changed: siren');
  add(dayAgo(2, 16, 10), 'zone_off', 'Window sensor turned off for at most 2 h');
  add(dayAgo(2, 17, 52), 'zone_on', 'Window sensor is active again');
  // armed intervals end by schedule unless an incident ended them earlier (kept simple: schedule end)
  intervals.forEach(iv => add(iv.end, 'disarmed', 'Schedule window ended, system disarmed'));
  events.sort((a, b) => a.ts - b.ts);
  events.forEach((e, i) => { e.id = i + 1; });
  return events;
}

// ------------------------------------------------------------------ insights (same maths as the Pi)
function buildInsights(events, now, days) {
  const [y, m, d] = localDate(now, TZ).split('-').map(Number);
  const bounds = [];
  const out = [];
  for (let i = 0; i < days; i += 1) {
    const dt = new Date(Date.UTC(y, m - 1, d - (days - 1 - i)));
    const Y = dt.getUTCFullYear();
    const M = dt.getUTCMonth() + 1;
    const D = dt.getUTCDate();
    bounds.push([zonedEpoch(Y, M, D, 0, 0, TZ), zonedEpoch(Y, M, D + 1, 0, 0, TZ)]);
    out.push({ date: `${Y}-${pad(M)}-${pad(D)}`, alarms: 0, triggers: 0, armed_s: 0 });
  }
  const first = bounds[0][0];
  const last = bounds[bounds.length - 1][1];
  const hours = new Array(24).fill(0);
  const bySensor = {};
  const totals = { alarms: 0, triggers: 0, clips: 0 };
  let lastAlarm = null;
  const intervals = [];
  let armedSince = null;

  [...events].sort((a, b) => a.ts - b.ts).forEach(e => {
    if ((e.kind === 'arming' || e.kind === 'restored') && armedSince == null) armedSince = e.ts;
    else if (e.kind === 'disarmed' && armedSince != null) {
      intervals.push([armedSince, e.ts]);
      armedSince = null;
    }
    if (e.ts < first || e.ts >= last) return;
    const idx = bounds.findIndex(([a, b]) => e.ts >= a && e.ts < b);
    if (e.kind === 'alarm') {
      out[idx].alarms += 1;
      totals.alarms += 1;
      lastAlarm = { ts: e.ts, text: e.text };
    } else if (e.kind === 'trigger') {
      out[idx].triggers += 1;
      totals.triggers += 1;
      const s = e.data?.sensor;
      if (s) bySensor[s] = (bySensor[s] || 0) + 1;
    } else if (e.kind === 'clips') totals.clips += e.data?.parts || 0;
    if (e.kind === 'alarm' || e.kind === 'trigger') hours[minutesOfDay(e.ts) / 60 | 0] += 1;
  });
  if (armedSince != null) intervals.push([armedSince, now]);
  intervals.forEach(([a, b]) => {
    bounds.forEach(([ds, de], i) => {
      const overlap = Math.min(b, de, now) - Math.max(a, ds);
      if (overlap > 0) out[i].armed_s += Math.floor(overlap);
    });
  });
  const armedTotal = out.reduce((s, x) => s + x.armed_s, 0);
  const elapsed = Math.max(1, Math.min(now, last) - first);
  return {
    days: out,
    hours,
    by_sensor: Object.entries(bySensor).sort((a, b) => b[1] - a[1]).map(([sensor, count]) => ({ sensor, count })),
    totals: { ...totals, armed_s: armedTotal, armed_pct: Math.round((1000 * armedTotal) / elapsed) / 10 },
    last_alarm: lastAlarm,
  };
}

// ------------------------------------------------------------------ simulation
function validate(settings) {
  const sc = settings.schedule;
  if (!sc.windows.every(w => w.days.length > 0)) return 'Pick at least one day for every window.';
  const okTime = t => /^([01]?\d|2[0-3]):[0-5]\d$/.test(t);
  if (!sc.windows.every(w => okTime(w.start) && okTime(w.end))) return 'Times must look like 08:30.';
  const q = settings.siren.quiet_hours;
  if (settings.siren.mode === 'quiet_hours' && q.start === q.end) return 'Quiet hours start and end must differ.';
  return null;
}

function deepMerge(base, patch) {
  const out = { ...base };
  Object.entries(patch).forEach(([k, v]) => {
    out[k] = v && typeof v === 'object' && !Array.isArray(v) && base[k] && typeof base[k] === 'object' ? deepMerge(base[k], v) : v;
  });
  return out;
}

export function createDemoClient() {
  const startedAt = Date.now() / 1000;
  const now = () => Date.now() / 1000;
  let settings = DEFAULT_SETTINGS();
  let events = seedHistory(now());
  let nextId = events.length + 1;
  const sensors = Object.fromEntries(
    SENSOR_DEFS.map(s => [s.name, { ...s, state: s.kind === 'contact' ? 'closed' : 'clear', lastSeen: now() - 40, pulseUntil: 0 }])
  );
  const smoke = { detected: false, until: 0 };
  let nextAmbient = now() + 20;
  let suspended = null;
  let cleanupLast = { at: now() - 11 * 3600, manual: false, folders: 2, rows: 7, skipped: null, error: null };
  let evt = null;
  const st = { state: 'disarmed', since: now(), deadline: null, armedBy: null, sirenUntil: null, alarmSilent: false, lastActivity: 0 };

  // begin consistent with the schedule: if a window is running right now, the room is already armed
  {
    const ev = evaluate(settings.schedule, now(), TZ);
    if (ev.active) {
      st.state = 'armed';
      st.armedBy = 'schedule';
      st.since = ev.window_start;
    }
  }

  const log = (kind, text, event_id = null, data = null) => {
    events.push({ id: nextId, ts: now(), kind, text, event_id, data });
    nextId += 1;
  };

  const vacationOn = t => {
    const v = settings.schedule.vacation;
    return !!v.active && (!v.until || t < v.until);
  };

  const exitDelay = () => settings.timing.exit_delay_s || BASE.exit;
  const entryDelay = () => settings.timing.entry_delay_s || BASE.entry;
  const sirenSeconds = () => settings.siren.duration_s || BASE.siren;
  const bypassed = name => !settings.sensors[name].enabled;
  const isSilent = t => settings.siren.mode === 'silent'
    || (settings.siren.mode === 'quiet_hours' && inDailyRange(t, settings.siren.quiet_hours.start, settings.siren.quiet_hours.end));
  const openOnes = () => SENSOR_DEFS.filter(s => s.kind === 'contact' && sensors[s.name].state === 'open' && !bypassed(s.name)).map(s => s.label);
  const busyOnes = t => SENSOR_DEFS.filter(s => s.kind === 'motion' && !bypassed(s.name) && t - sensors[s.name].lastActive < settings.schedule.busy_s).map(s => s.label);
  SENSOR_DEFS.forEach(s => { sensors[s.name].lastActive = 0; });

  const doArm = (by, t) => {
    st.state = 'exit_delay';
    st.since = t;
    st.deadline = t + exitDelay();
    st.armedBy = by;
    const off = SENSOR_DEFS.filter(s => bypassed(s.name)).map(s => s.label);
    log('arming', `${by === 'schedule' ? 'Auto-arming by schedule' : 'Arming'}, leave within ${exitDelay()} s${off.length ? ` (sensors off: ${off.join(', ')})` : ''}`);
  };

  const doDisarm = (by, t) => {
    if (st.sirenUntil) st.sirenUntil = null;
    const prev = st.state;
    evt = null;
    st.state = 'disarmed';
    st.since = t;
    st.deadline = null;
    st.alarmSilent = false;
    log('disarmed', by === 'schedule' ? 'Schedule window ended, system disarmed'
      : prev === 'entry_delay' ? 'Disarmed during entry delay (no alarm)'
        : prev === 'alarm' ? 'Disarmed while alarm was active' : 'System disarmed');
  };

  const toAlarm = (reason, t) => {
    st.state = 'alarm';
    st.since = t;
    st.deadline = null;
    st.lastActivity = t;
    st.alarmSilent = isSilent(t);
    st.sirenUntil = st.alarmSilent ? null : t + sirenSeconds();
    evt.alarmAt = t;
    log('alarm', `ALARM: ${reason}${st.alarmSilent ? ' (silent: siren muted)' : ''}`, evt.id);
  };

  const trigger = (name, t) => {
    const def = SENSOR_DEFS.find(s => s.name === name);
    const reason = def.kind === 'motion' ? `Motion: ${def.label}` : `${def.label} opened`;
    if (st.state === 'armed') {
      evt = { id: `${Math.floor(t)}-demo`, reason, started: t, alarmAt: null };
      log('trigger', reason, evt.id, { sensor: name });
      const view = settings.camera.follow ? settings.camera.views[name] : null;
      const viewName = ptzPresets.find(p => p.id === view)?.name;
      if (viewName) log('camera', `Camera turned to saved view "${viewName}" (${name})`);
      if (!def.entry) toAlarm(reason, t);
      else {
        st.state = 'entry_delay';
        st.since = t;
        st.deadline = t + entryDelay();
      }
    } else if (st.state === 'entry_delay' && !def.entry) toAlarm(reason, t);
    else if (st.state === 'alarm') st.lastActivity = t;
  };

  function tick() {
    const t = now();
    if (st.state === 'exit_delay' && t >= st.deadline) {
      st.state = 'armed';
      st.since = t;
      st.deadline = null;
      log('armed', 'System armed');
    } else if (st.state === 'entry_delay' && t >= st.deadline) toAlarm(`Entry delay expired (${evt.reason})`, t);

    if (st.state === 'alarm') {
      if (st.sirenUntil && t >= st.sirenUntil) st.sirenUntil = null;
      if (t - st.lastActivity >= 120) {
        log('alarm_end', 'Activity ended, recording closed', evt.id);
        const folder = folderName(evt.alarmAt, 'demo');
        log('clips', `3 clip(s) saved to cloud folder ${folder}`, evt.id, { parts: 3, folder });
        evt = null;
        st.state = 'armed';
        st.since = t;
        st.alarmSilent = false;
      }
    }

    // sensor switch-off timers
    Object.entries(settings.sensors).forEach(([name, z]) => {
      if (z.enabled) return;
      const s = sensors[name];
      let expired = !!(z.until && t >= z.until);
      if (!expired && z.until_closed) {
        if (s.state === 'open' && !z.saw_open) z.saw_open = true;
        else if (s.state === 'closed' && z.saw_open) expired = true;
      }
      if (expired) {
        Object.assign(z, { enabled: true, until: null, until_closed: false, saw_open: false });
        log('zone_on', `${s.label} sensor is active again`);
      }
    });

    // schedule automation
    const sc = settings.schedule;
    if (sc.paused_until && t >= sc.paused_until) sc.paused_until = null;
    const ev = evaluate(sc, t, TZ);
    if (sc.vacation.active && !vacationOn(t)) {                // the planned end date has passed
      sc.vacation = { active: false, since: null, until: null };
      if (suspended === 'vacation') suspended = null;
      if (st.armedBy === 'schedule' && st.state !== 'disarmed') doDisarm('schedule', t);
      log('vacation', 'Vacation mode ended. Welcome back.');
    }
    if (vacationOn(t)) {
      if (suspended !== 'vacation' && st.state === 'disarmed' && openOnes().length === 0 && !(sc.smart_arm && busyOnes(t).length)) doArm('schedule', t);
    } else if (sc.enabled && !sc.paused_until) {
      const sus = ev.window_start != null && suspended === ev.window_start;
      if (ev.active) {
        if (!sus && st.state === 'disarmed' && openOnes().length === 0 && !(sc.smart_arm && busyOnes(t).length)) doArm('schedule', t);
      } else if (sc.auto_disarm && st.armedBy === 'schedule' && ['exit_delay', 'armed', 'entry_delay'].includes(st.state)) doDisarm('schedule', t);
    }

    // ambient life while disarmed: the motion sensor wakes up now and then
    const motion = sensors.motion;
    if (motion.state === 'motion' && t >= motion.pulseUntil) motion.state = 'clear';
    if (st.state === 'disarmed' && t >= nextAmbient) {
      motion.state = 'motion';
      motion.lastActive = t;
      motion.lastSeen = t;
      motion.pulseUntil = t + 4;
      nextAmbient = t + 25 + Math.random() * 45;
    }
    if (smoke.detected && t >= smoke.until) smoke.detected = false;
    return { t, ev };
  }

  function scheduleStatus(t, ev) {
    const sc = settings.schedule;
    const paused = !!sc.paused_until;
    const vac = vacationOn(t);
    const sus = vac ? suspended === 'vacation' : ev.window_start != null && suspended === ev.window_start;
    let state = 'off';
    let reason = null;
    if (vac) {
      if (sus) { state = 'suspended'; reason = 'You disarmed manually. Press Resume to let vacation mode arm again.'; }
      else if (st.state !== 'disarmed') state = 'vacation';
      else {
        const b = openOnes();
        state = 'postponed';
        reason = b.length ? `${b.join(', ')} open` : 'Movement seen in the room';
      }
    } else if (sc.enabled) {
      if (paused) state = 'paused';
      else if (ev.active) {
        if (sus) { state = 'suspended'; reason = 'You disarmed manually. Press Resume to let the schedule arm again.'; }
        else if (st.state !== 'disarmed') state = 'armed';
        else {
          const b = openOnes();
          const busy = sc.smart_arm ? busyOnes(t) : [];
          state = 'postponed';
          reason = b.length ? `${b.join(', ')} open` : `Movement seen by ${busy.join(', ')}`;
        }
      } else state = ev.skipped_now ? 'skipped' : 'idle';
    }
    return { enabled: sc.enabled, state, reason, active: ev.active, window_start: ev.window_start, window_end: ev.window_end,
      next_start: ev.next_start, next_end: ev.next_end, skipped_now: ev.skipped_now, skipped_next: ev.skipped_next,
      paused_until: sc.paused_until, suspended: sus, vacation: { active: vac, since: sc.vacation.since, until: sc.vacation.until } };
  }

  const effective = () => ({ exit_delay_s: exitDelay(), entry_delay_s: entryDelay(), siren_duration_s: sirenSeconds() });
  const copy = o => JSON.parse(JSON.stringify(o));

  return {
    kind: 'demo',
    configured: true,
    liveHeaders: {},

    async status() {
      const { t, ev } = tick();
      const watching = ['armed', 'entry_delay', 'alarm'].includes(st.state);
      return {
        state: st.state,
        since: st.since,
        remaining_s: st.deadline && (st.state === 'exit_delay' || st.state === 'entry_delay') ? Math.max(0, Math.round(st.deadline - t)) : null,
        armed: st.state !== 'disarmed',
        siren_active: !!st.sirenUntil,
        siren_silent: isSilent(t),
        alarm_silent: st.alarmSilent && st.state === 'alarm',
        armed_by: st.state !== 'disarmed' ? st.armedBy : null,
        camera_ok: true,
        zigbee_ok: true,
        event: evt ? { id: evt.id, reason: evt.reason, started: evt.started } : null,
        sensors: SENSOR_DEFS.map(def => {
          const s = sensors[def.name];
          const z = settings.sensors[def.name];
          return {
            name: def.name, label: def.label, kind: def.kind, state: s.state, tamper: false, battery: def.battery,
            online: true, last_seen: s.lastSeen, linkquality: def.lq, bypassed: !z.enabled, enabled: z.enabled,
            bypass_until: z.until, bypass_until_closed: z.until_closed,
          };
        }),
        version: 'demo',
        uptime_s: Math.round(t - startedAt) + 12 * 86400 + 3600 * 5,
        mqtt_ok: true,
        cloud: { configured: true, pending_files: st.state === 'alarm' ? 2 : 0, pending_mb: st.state === 'alarm' ? 18.4 : 0, last_ok: t - 600, last_error: null },
        recording: { capturing: watching, event_id: evt?.id ?? null, uploading: st.state === 'alarm', parts: st.state === 'alarm' ? 2 : 0 },
        siren_enabled: true,
        siren_mode: settings.siren.mode,
        timezone: TZ,
        retention: {
          days: settings.cloud.retention_days, hold: vacationOn(t), at: '03:30',
          last: cleanupLast, usage: { bytes: Math.round(1.38 * 1024 ** 3), count: 212, at: t - 3600 },
        },
        schedule: scheduleStatus(t, ev),
        system: {
          cpu_temp_c: Math.round((46 + 3 * Math.sin(t / 300)) * 10) / 10, load1: 0.31, mem_used_pct: 38.2,
          disk_used_pct: 23.4, disk_free_gb: 22.7, host_uptime_s: Math.round(t - startedAt) + 12 * 86400 + 3600 * 5,
        },
        server_time: t,
      };
    },

    async events(limit = 100) {
      tick();
      return [...events].reverse().slice(0, limit);
    },
    async insights(days = 14) {
      tick();
      return buildInsights(events, now(), days);
    },
    async settings() {
      return { settings: copy(settings), effective: effective(), timezone: TZ };
    },
    async saveSettings(patch) {
      const next = deepMerge(copy(settings), patch);
      Object.keys(next.camera.views).forEach(k => { if (next.camera.views[k] === null) delete next.camera.views[k]; });   // null = no view
      const problem = validate(next);
      if (problem) return { ok: false, error: 'invalid', detail: problem };
      settings = next;
      log('settings', `Settings changed: ${Object.keys(patch).join(', ')}`);
      return { ok: true, settings: copy(settings), effective: effective(), timezone: TZ };
    },

    async arm(force = false) {
      const t = now();
      if (st.state !== 'disarmed') return { ok: false, error: 'not_disarmed', state: st.state };
      const open = openOnes();
      if (open.length && !force) return { ok: false, error: 'open_sensors', open };
      suspended = null;
      doArm('user', t);
      return { ok: true, state: st.state };
    },
    async disarm() {
      const t = now();
      const was = st.state !== 'disarmed';
      doDisarm('user', t);
      const res = { ok: true, state: 'disarmed' };
      const ev = evaluate(settings.schedule, t, TZ);
      if (was && vacationOn(t)) {
        suspended = 'vacation';
        log('schedule', 'Vacation arming paused (you disarmed manually)');
        res.schedule_suspended = true;
      } else if (was && settings.schedule.enabled && ev.active) {
        suspended = ev.window_start;
        log('schedule', 'Auto-arm paused until this window ends (you disarmed manually)');
        res.schedule_suspended = true;
      }
      return res;
    },
    async silence() {
      if (!st.sirenUntil) return { ok: false, error: 'siren_not_sounding' };
      st.sirenUntil = null;
      log('siren_silenced', 'Siren silenced from the app (recording continues)', evt?.id ?? null);
      return { ok: true };
    },
    async testSiren() {
      return st.state === 'disarmed' ? { ok: true } : { ok: false, error: 'not_disarmed' };
    },
    async testPush() {
      return { ok: true, delivered: 1 };
    },

    async setSensor(name, enabled, { minutes, untilClosed } = {}) {
      const z = settings.sensors[name];
      const s = sensors[name];
      if (!z) return { ok: false, error: 'unknown_sensor' };
      if (enabled) {
        Object.assign(z, { enabled: true, until: null, until_closed: false, saw_open: false });
        log('zone_on', `${s.label} sensor turned back on`);
      } else {
        Object.assign(z, { enabled: false, until: minutes ? now() + minutes * 60 : null, until_closed: !!untilClosed, saw_open: s.state === 'open' });
        const how = [untilClosed ? 'until it is closed again' : null, minutes ? `for at most ${minutes >= 60 ? `${minutes / 60} h` : `${minutes} min`}` : null].filter(Boolean).join(', ');
        log('zone_off', `${s.label} sensor turned off ${how || 'until you turn it back on'}`);
      }
      return { ok: true };
    },
    async skipDay(date, skip = true) {
      const t = now();
      let day = date;
      if (date === 'today') day = localDate(t, TZ);
      if (date === 'tomorrow') day = localDate(t + 86400, TZ);
      const set = new Set(settings.schedule.skip_dates);
      if (skip) set.add(day); else set.delete(day);
      settings.schedule.skip_dates = [...set].sort();
      log('schedule', `${day} marked as ${skip ? 'a day at home (schedule skipped)' : 'a normal day'}`);
      return { ok: true, date: day, skipped: skip };
    },
    async pause(minutes) {
      settings.schedule.paused_until = minutes ? now() + minutes * 60 : null;
      log('schedule', minutes ? `Schedule paused for ${minutes >= 60 ? `${minutes / 60} h` : `${minutes} min`}` : 'Schedule pause cleared');
      return { ok: true, paused_until: settings.schedule.paused_until };
    },
    async resume() {
      suspended = null;
      settings.schedule.paused_until = null;
      log('schedule', 'Schedule resumed');
      return { ok: true };
    },

    // ---- vacation, storage and recordings
    async vacation(active, days) {
      const t = now();
      const sc = settings.schedule;
      if (active) {
        sc.vacation = { active: true, since: t, until: days ? t + days * 86400 : null };
        suspended = null;
        log('vacation', `Vacation mode on, armed day and night ${days ? `for ${days} days` : 'until you turn it off'}`);
      } else if (sc.vacation.active) {
        sc.vacation = { active: false, since: null, until: null };
        if (suspended === 'vacation') suspended = null;
        if (st.armedBy === 'schedule' && st.state !== 'disarmed') doDisarm('schedule', t);
        log('vacation', 'Vacation mode turned off. Welcome back.');
      }
      tick();
      return { ok: true, vacation: copy(sc.vacation) };
    },
    async cleanup() {
      const t = now();
      const cutoff = t - settings.cloud.retention_days * 86400;
      const old = events.filter(e => e.ts < cutoff);
      events = events.filter(e => e.ts >= cutoff);
      cleanupLast = { at: t, manual: true, folders: old.filter(e => e.kind === 'clips').length, rows: old.length, skipped: settings.cloud.retention_days ? null : 'keep_forever', error: null };
      return { ok: true, result: cleanupLast };
    },
    async eventClips(eventId) {
      const e = events.find(x => x.event_id === eventId && x.kind === 'clips');
      if (!e) return { event_id: eventId, folder: null, error: null, recording: false, clips: [] };
      const parts = e.data?.parts ?? 3;
      const clips = Array.from({ length: parts }, (_, i) => ({ name: `part_${String(i + 1).padStart(3, '0')}.mp4`, size: (4 + ((i * 7) % 9)) * 1024 * 1024, kind: 'video', where: 'cloud' }));
      clips.push({ name: 'snapshot.jpg', size: 96 * 1024, kind: 'image', where: 'cloud' });
      return { event_id: eventId, folder: e.data?.folder ?? null, error: null, recording: false, clips };
    },
    clipSource: (eventId, name) => (name.endsWith('.jpg') ? ROOM_IMAGE : DEMO_CLIP),

    async liveUrl() {
      return null; // the Camera screen shows a simulated feed in demo mode
    },
    snapshotSource: () => ROOM_IMAGE,

    // ---- camera pan / tilt: a pretend camera with three saved views
    async ptzInfo() {
      return { supported: true, speed: 'normal', speeds: ['slow', 'normal', 'fast'], arm_preset: 1, presets: ptzPresets.map(p => ({ ...p })) };
    },
    async ptzMove() { return { ok: true }; },
    async ptzStop() { return { ok: true }; },
    async ptzGo() { return { ok: true }; },
    async ptzSave(name) {
      const id = Math.max(0, ...ptzPresets.map(p => p.id)) + 1;
      ptzPresets.push({ id, name });
      return { ok: true, id, name };
    },
    async ptzDelete(id) {
      ptzPresets = ptzPresets.filter(p => p.id !== id);
      return { ok: true };
    },
    async registerPush() {},

    async smoke() {
      tick();
      return {
        name: 'Smoke Sentry', rssi: -58, uptime: '6d 4h', heap: '148 KB', sensorReady: true,
        smokeDetected: smoke.detected, alarmActive: smoke.detected, fw: '0.3.1',
      };
    },
    smokeSnapshotSource: () => ROOM_IMAGE,
    smokeAlertPhotoSource: () => ROOM_IMAGE,
    async registerSmokePush() {},

    // ---- demo-only controls (the UI only offers these when kind === 'demo')
    async simulate(what) {
      const t = now();
      if (what === 'smoke') {
        smoke.detected = true;
        smoke.until = t + 20;
        return { ok: true };
      }
      const s = sensors[what];
      if (!s) return { ok: false };
      s.lastSeen = t;
      if (s.kind === 'contact') s.state = 'open';
      else { s.state = 'motion'; s.lastActive = t; s.pulseUntil = t + 4; }
      if (!bypassed(what)) trigger(what, t);
      return { ok: true };
    },
    async closeAll() {
      SENSOR_DEFS.filter(s => s.kind === 'contact').forEach(s => { sensors[s.name].state = 'closed'; });
      return { ok: true };
    },
    async reset() {
      settings = DEFAULT_SETTINGS();
      events = seedHistory(now());
      nextId = events.length + 1;
      evt = null;
      suspended = null;
      cleanupLast = { at: now() - 11 * 3600, manual: false, folders: 2, rows: 7, skipped: null, error: null };
      Object.assign(st, { state: 'disarmed', since: now(), deadline: null, armedBy: null, sirenUntil: null, alarmSilent: false });
      SENSOR_DEFS.forEach(s => { sensors[s.name].state = s.kind === 'contact' ? 'closed' : 'clear'; });
      const ev = evaluate(settings.schedule, now(), TZ);
      if (ev.active) { st.state = 'armed'; st.armedBy = 'schedule'; st.since = ev.window_start; }
      return { ok: true };
    },
  };
}
