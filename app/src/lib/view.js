/** Presentation rules shared by several screens: how a state looks, what an event is, what a week holds. */
import { fmtDateShort, fmtDayTime } from '../format.js';

export function stateView(st, remaining) {
  const sub = {
    armed: `${st?.armed_by === 'schedule' ? 'Armed by the schedule. ' : st?.armed_by === 'user' ? 'Armed by you. ' : ''}The room is being watched.`,
  };
  switch (st?.state) {
    case 'armed':
      return { icon: 'shield-check', tone: 'success', title: 'Armed', sub: sub.armed, wash: 'heroArmed' };
    case 'exit_delay':
      return { icon: 'timer-sand', tone: 'primary', title: `Leave now · ${remaining ?? 0} s`, sub: 'The room arms when the countdown ends.', wash: 'heroBusy' };
    case 'entry_delay':
      return { icon: 'alert', tone: 'warning', title: `Disarm within ${remaining ?? 0} s`, sub: `${st.event?.reason ?? 'Entry detected'}. The alarm sounds when this ends.`, wash: 'heroWarn' };
    case 'alarm': {
      const siren = st.siren_active ? 'Siren sounding.' : st.alarm_silent ? 'Silent alarm: siren is off.' : 'Siren silenced.';
      return {
        icon: 'alarm-light', tone: 'danger', title: st.alarm_silent ? 'Silent alarm' : 'Alarm',
        sub: `${st.event?.reason ?? 'Intrusion'}. ${siren} Recording to the cloud.`, wash: 'heroDanger',
      };
    }
    case 'disarmed':
      return { icon: 'shield-off-outline', tone: 'neutral', title: 'Disarmed', sub: 'Nothing is being recorded.', wash: 'heroIdle' };
    default:
      return { icon: 'shield-outline', tone: 'neutral', title: 'Connecting', sub: 'Waiting for the Pi.', wash: 'heroIdle' };
  }
}

export const SIREN_MODE_LABEL = { on: 'Siren on', silent: 'Silent', quiet_hours: 'Quiet hours' };

/** One-line schedule description for cards and the settings list. */
export function scheduleLine(st, tz, nowS) {
  const sc = st?.schedule;
  if (sc?.vacation?.active) {
    const until = sc.vacation.until ? ` until ${fmtDateShort(sc.vacation.until, tz)}` : '';
    if (sc.state === 'suspended') return 'Vacation mode paused: you disarmed manually';
    if (sc.state === 'postponed') return `Vacation mode: waiting to arm (${sc.reason})`;
    return `Vacation mode: armed day and night${until}`;
  }
  if (!sc?.enabled) return 'Automatic arming is off.';
  const next = sc.next_start ? `Next: arms ${fmtDayTime(sc.next_start, tz, nowS)}` : 'No upcoming window';
  switch (sc.state) {
    case 'armed':
      return st.armed_by === 'schedule'
        ? `Armed by the schedule until ${fmtDayTime(sc.window_end, tz, nowS)}`
        : `Armed by you · window ends ${fmtDayTime(sc.window_end, tz, nowS)}`;
    case 'postponed': return `Waiting to arm: ${sc.reason}`;
    case 'suspended': return 'Paused for this window: you disarmed manually';
    case 'paused': return `Paused until ${fmtDayTime(sc.paused_until, tz, nowS)}`;
    case 'skipped': return `Day at home · ${sc.next_start ? `next arms ${fmtDayTime(sc.next_start, tz, nowS)}` : 'no upcoming window'}`;
    default: return next;
  }
}

export function scheduleTone(sc) {
  if (sc?.vacation?.active) return sc.state === 'suspended' || sc.state === 'postponed' ? 'warning' : 'info';
  if (!sc?.enabled) return 'neutral';
  return { armed: 'success', postponed: 'warning', suspended: 'warning', paused: 'warning', skipped: 'info', idle: 'primary' }[sc.state] ?? 'neutral';
}

export function scheduleLabel(sc) {
  if (sc?.vacation?.active) return sc.state === 'suspended' ? 'Paused' : sc.state === 'postponed' ? 'Waiting' : 'Vacation';
  if (!sc?.enabled) return 'Off';
  return { armed: 'Active', postponed: 'Waiting', suspended: 'Paused', paused: 'Paused', skipped: 'Day at home', idle: 'Scheduled' }[sc.state] ?? 'On';
}

// ---------------------------------------------------------------- events
const CATEGORY = {
  alarm: 'alarms', trigger: 'alarms', tamper: 'alarms', alarm_end: 'alarms', siren_silenced: 'alarms', clips: 'alarms',
  arming: 'arming', armed: 'arming', disarmed: 'arming', restored: 'arming', schedule: 'arming',
  battery: 'devices', sensor_offline: 'devices', sensor_online: 'devices', zone_on: 'devices', zone_off: 'devices',
  camera_down: 'devices', zigbee_down: 'devices', zigbee_up: 'devices',
  vacation: 'arming', camera: 'alarms', cleanup: 'system',
};

const META = {
  alarm: ['alarm-light', 'danger'], trigger: ['alert', 'warning'], tamper: ['alert-octagon', 'danger'],
  alarm_end: ['check-circle-outline', 'neutral'], siren_silenced: ['volume-off', 'info'], clips: ['cloud-check-outline', 'success'],
  arming: ['timer-sand', 'primary'], armed: ['shield-check', 'success'], disarmed: ['shield-off-outline', 'neutral'],
  restored: ['refresh', 'neutral'], schedule: ['calendar-clock', 'primary'],
  battery: ['battery-20', 'warning'], sensor_offline: ['wifi-off', 'warning'], sensor_online: ['wifi', 'success'],
  zone_on: ['eye-outline', 'success'], zone_off: ['eye-off-outline', 'info'], camera_down: ['video-off', 'warning'],
  zigbee_down: ['wifi-off', 'warning'], zigbee_up: ['wifi', 'success'], settings: ['tune-variant', 'neutral'],
  vacation: ['airplane', 'info'], camera: ['cctv', 'primary'], cleanup: ['broom', 'neutral'],
};

export const eventCategory = kind => CATEGORY[kind] ?? 'system';
export const eventMeta = kind => {
  const [icon, tone] = META[kind] ?? ['information-outline', 'neutral'];
  return { icon, tone };
};

export const EVENT_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'alarms', label: 'Alarms' },
  { value: 'arming', label: 'Arming' },
  { value: 'devices', label: 'Devices' },
];

/** Which events belong to one incident (same event_id), oldest first. */
export function incidentEvents(events, eventId) {
  return (events ?? []).filter(e => e.event_id === eventId).sort((a, b) => a.ts - b.ts);
}

export function incidentSummary(list) {
  const kinds = new Set(list.map(e => e.kind));
  const alarm = list.find(e => e.kind === 'alarm');
  const trigger = list.find(e => e.kind === 'trigger');
  const clips = list.find(e => e.kind === 'clips');
  const silent = !!alarm && alarm.text.includes('silent');
  if (alarm) {
    return {
      tone: 'danger', icon: 'alarm-light', title: silent ? 'Silent alarm' : 'Alarm',
      sub: trigger?.text ?? alarm.text, silent, clips: clips?.data ?? null, kinds,
    };
  }
  return { tone: 'warning', icon: 'alert', title: 'False alarm', sub: `${trigger?.text ?? 'Entry'} · disarmed in time`, silent: false, clips: null, kinds };
}

// ---------------------------------------------------------------- sensors
export function sensorView(s) {
  const off = s.enabled === false;
  const isContact = s.kind === 'contact';
  const isDoor = /door/i.test(s.name + s.label);
  const open = s.state === 'open';
  const active = s.state === 'open' || s.state === 'motion';
  const icon = isContact
    ? isDoor ? (open ? 'door-open' : 'door-closed') : open ? 'window-open-variant' : 'window-closed-variant'
    : 'motion-sensor';
  const text = off ? 'Off' : { open: 'Open', closed: 'Closed', motion: 'Motion', clear: 'Clear' }[s.state] ?? '—';
  const tone = off ? 'neutral' : active ? 'warning' : s.state === 'unknown' ? 'neutral' : 'success';
  return { icon, text, tone, off };
}

// ---------------------------------------------------------------- week plan
const WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** The next `count` days as the schedule sees them: [{ iso, wd, label, num, kind: 'armed'|'home'|'none', times }] */
export function weekPlan(sched, days) {
  return days.map(d => {
    const wins = sched.windows.filter(w => w.days.includes(d.wd));
    const skipped = sched.skip_dates.includes(d.iso) || sched.home_weekdays.includes(d.wd);
    const kind = !wins.length ? 'none' : skipped ? 'home' : 'armed';
    return { ...d, label: WD[d.wd], kind, times: wins.map(w => `${w.start}–${w.end}`) };
  });
}

// ---------------------------------------------------------------- recordings & storage
export function fmtBytes(n) {
  if (!Number.isFinite(n) || n < 0) return '—';
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(n < 10 * 1024 ** 2 ? 1 : 0)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

export const RETENTION_CHOICES = [
  { value: 7, label: '7 days' }, { value: 15, label: '15 days' }, { value: 30, label: '30 days' },
  { value: 60, label: '60 days' }, { value: 0, label: 'Keep all' },
];

/** Plain words for the result of a clean-up run (the Pi's `retention.last`). */
export function cleanupLine(last) {
  if (!last) return 'Not run yet';
  if (last.skipped === 'vacation') return 'Skipped: you were on vacation';
  if (last.skipped === 'keep_forever') return 'Skipped: recordings are kept for ever';
  const parts = [`${last.folders} recording${last.folders === 1 ? '' : 's'}`, `${last.rows} alert${last.rows === 1 ? '' : 's'}`];
  return `Deleted ${parts.join(' and ')}${last.error ? ' (incomplete: Drive did not answer)' : ''}`;
}
