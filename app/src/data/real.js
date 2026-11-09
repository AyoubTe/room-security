/**
 * The real client: the Raspberry Pi service (/api/...) and the ESP32 smoke detector.
 * Same interface as the demo client (demo.js), so no screen knows which one it is using.
 */
import { ESP32_API, SENTINEL_API, SENTINEL_CONFIGURED, SENTINEL_TOKEN } from '../config.js';

const AUTH = { Authorization: `Bearer ${SENTINEL_TOKEN}` };

async function call(path, { method = 'GET', body } = {}) {
  const r = await fetch(`${SENTINEL_API}${path}`, {
    method,
    headers: { ...AUTH, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try {
    data = await r.json();
  } catch {
    // non-JSON body (a proxy error page, say): leave data as null
  }
  return { ok: r.ok, status: r.status, data };
}

const flat = ({ ok, data }) => ({ ok, ...(data || {}) });

function uptimeText(totalSeconds) {
  const d = Math.floor(totalSeconds / 86400);
  const h = Math.floor((totalSeconds % 86400) / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  return d > 0 ? `${d}d ${h}h` : `${h}h ${m}m`;
}

// Camera movements must reach the Pi in the order they were pressed (a Stop must never overtake its Move).
let ptzChain = Promise.resolve();
function ptzCall(path, body) {
  const run = () => call(path, { method: 'POST', body: body ?? {} });
  const next = ptzChain.then(run, run);
  ptzChain = next.catch(() => {});
  return next;
}

export function createRealClient() {
  return {
    kind: 'live',
    configured: SENTINEL_CONFIGURED,
    liveHeaders: AUTH,

    async status() {
      if (!SENTINEL_CONFIGURED) throw new Error('The Pi is not set up yet. Fill in src/config.js.');
      const { ok, status, data } = await call('/api/status');
      if (!ok) throw new Error(status === 401 ? 'Wrong SENTINEL_TOKEN' : `Pi answered ${status}`);
      return data;
    },
    async events(limit = 100) {
      const { ok, data } = await call(`/api/events?limit=${limit}`);
      if (!ok) throw new Error('events unavailable');
      return data.events;
    },
    async insights(days = 14) {
      const { ok, data } = await call(`/api/insights?days=${days}`);
      if (!ok) throw new Error('insights unavailable');
      return data;
    },
    async settings() {
      const { ok, status, data } = await call('/api/settings');
      if (!ok) throw new Error(`settings ${status}`);
      return data;
    },
    saveSettings: async patch => flat(await call('/api/settings', { method: 'POST', body: patch })),

    arm: async (force = false) => flat(await call('/api/arm', { method: 'POST', body: { force } })),
    disarm: async () => flat(await call('/api/disarm', { method: 'POST', body: {} })),
    silence: async () => flat(await call('/api/siren/silence', { method: 'POST', body: {} })),
    testSiren: async () => flat(await call('/api/siren/test', { method: 'POST', body: {} })),
    testPush: async () => flat(await call('/api/test-push', { method: 'POST', body: {} })),

    setSensor: async (name, enabled, { minutes, untilClosed } = {}) => {
      const body = { enabled };
      if (minutes) body.minutes = minutes;
      if (untilClosed) body.until_closed = true;
      return flat(await call(`/api/sensors/${encodeURIComponent(name)}`, { method: 'POST', body }));
    },
    skipDay: async (date, skip = true) => flat(await call('/api/schedule/skip', { method: 'POST', body: { date, skip } })),
    pause: async minutes => flat(await call('/api/schedule/pause', { method: 'POST', body: { minutes } })),
    resume: async () => flat(await call('/api/schedule/resume', { method: 'POST', body: {} })),

    // ---- vacation mode and storage clean-up
    vacation: async (active, days) => flat(await call('/api/vacation', { method: 'POST', body: days ? { active, days } : { active } })),
    cleanup: async () => flat(await call('/api/cloud/cleanup', { method: 'POST', body: {} })),

    // ---- recordings of an incident: listed by the Pi, streamed through it (Drive stays private)
    async eventClips(eventId) {
      const { ok, status, data } = await call(`/api/events/${encodeURIComponent(eventId)}/clips`);
      if (status === 404) return { clips: [], folder: null, error: null, gone: true };
      if (!ok) throw new Error(`recordings unavailable (${status})`);
      return data;
    },
    clipSource: (eventId, name) => ({
      uri: `${SENTINEL_API}/api/events/${encodeURIComponent(eventId)}/clips/${encodeURIComponent(name)}`,
      headers: AUTH,
    }),

    async liveUrl() {
      const { ok, data } = await call('/api/live');
      if (!ok) throw new Error('live view unavailable');
      return data.hls;
    },
    snapshotSource: () => ({ uri: `${SENTINEL_API}/api/snapshot?t=${Date.now()}`, headers: AUTH }),

    // ---- camera pan / tilt (the Pi talks to the Reolink)
    async ptzInfo() {
      const { ok, data } = await call('/api/ptz');
      if (!ok) throw new Error('camera controls unavailable');
      return data;
    },
    ptzMove: async (direction, seconds, speed) => flat(await ptzCall('/api/ptz/move', { direction, seconds, speed })),
    ptzStop: async () => flat(await ptzCall('/api/ptz/stop')),
    ptzGo: async id => flat(await ptzCall('/api/ptz/preset/go', { id })),
    ptzSave: async name => flat(await ptzCall('/api/ptz/preset/save', { name })),
    ptzDelete: async id => flat(await ptzCall('/api/ptz/preset/delete', { id })),

    async registerPush(token) {
      const { ok, status } = await call('/api/register', { method: 'POST', body: { token } });
      if (!ok) throw new Error(`/api/register responded ${status}`);
    },

    // ---- ESP32 smoke detector
    async smoke() {
      const r = await fetch(`${ESP32_API}/status`);
      if (!r.ok) throw new Error(`/status responded ${r.status}`);
      const d = await r.json();
      return {
        name: d.location,
        rssi: d.rssi,
        uptime: uptimeText(d.uptime),
        heap: `${Math.round(d.heap / 1024)} KB`,
        sensorReady: d.sensor === 'ready',
        smokeDetected: d.mq2 === 1,
        alarmActive: d.alarm === 'trip',
        fw: d.fw,
      };
    },
    smokeSnapshotSource: () => ({ uri: `${ESP32_API}/capture?t=${Date.now()}` }),
    smokeAlertPhotoSource: () => ({ uri: `${ESP32_API}/alert.jpg?t=${Date.now()}` }),
    async registerSmokePush(token) {
      const r = await fetch(`${ESP32_API}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      });
      if (!r.ok) throw new Error(`/register responded ${r.status}`);
    },
  };
}
