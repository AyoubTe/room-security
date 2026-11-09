import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { SENTINEL_CONFIGURED } from '../config.js';
import { load, save } from '../theme/storage.js';
import { createDemoClient } from './demo.js';
import { createRealClient } from './real.js';

const KEY = 'pref.source';
const DataContext = createContext(null);

/** Call `fn(client)` every `ms` (and again whenever `tick` changes) and hand each result to `onResult`. */
function usePoll(client, tick, fn, ms, onResult) {
  const latest = useRef({ fn, onResult });
  useEffect(() => {
    latest.current = { fn, onResult };
  });
  useEffect(() => {
    if (!client) return undefined;
    let cancelled = false;
    let timer = null;
    const run = async () => {
      if (cancelled) return;
      try {
        const data = await latest.current.fn(client);
        if (!cancelled) latest.current.onResult({ ok: true, data });
      } catch (e) {
        if (!cancelled) latest.current.onResult({ ok: false, error: String(e.message || e) });
      }
      if (!cancelled) timer = setTimeout(run, ms);
    };
    run();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [client, tick, ms]);
}

const EMPTY_PI = { online: false, status: null, error: null, at: null, loaded: false };

/**
 * Single source of truth for every screen. It owns the client (demo or live, remembered between
 * launches), polls it, and exposes plain data plus actions. Screens never call the network.
 */
export function DataProvider({ children }) {
  const [source, setSource] = useState(null); // 'demo' | 'live', null while loading the preference
  const [demoClient] = useState(createDemoClient);
  const [realClient] = useState(createRealClient);
  const [tick, setTick] = useState(0);

  const [pi, setPi] = useState(EMPTY_PI);
  const [smoke, setSmoke] = useState({ online: false, device: null, at: null });
  const [events, setEvents] = useState({ list: null, error: null });
  const [insights, setInsights] = useState(null);
  const [settings, setSettings] = useState(null); // { settings, effective, timezone }

  useEffect(() => {
    let off = false;
    load(KEY, null).then(v => {
      if (off) return;
      setSource(v === 'demo' || v === 'live' ? v : SENTINEL_CONFIGURED ? 'live' : 'demo');
    });
    return () => {
      off = true;
    };
  }, []);

  const client = source === 'demo' ? demoClient : source === 'live' ? realClient : null;

  const chooseSource = useCallback(next => {
    setSource(next);
    save(KEY, next);
    setPi(EMPTY_PI);
    setSmoke({ online: false, device: null, at: null });
    setEvents({ list: null, error: null });
    setInsights(null);
    setSettings(null);
  }, []);

  const refresh = useCallback(() => setTick(n => n + 1), []);

  usePoll(client, tick, c => c.status(), 2000, ({ ok, data, error }) => {
    setPi(prev => ok
      ? { online: true, status: data, error: null, at: Date.now(), loaded: true }
      : { ...prev, online: false, error, loaded: true });
  });
  usePoll(client, tick, c => c.smoke(), 3000, ({ ok, data }) => {
    setSmoke(prev => (ok ? { online: true, device: data, at: Date.now() } : { ...prev, online: false }));
  });
  usePoll(client, tick, c => c.events(120), 8000, ({ ok, data, error }) => {
    setEvents(prev => (ok ? { list: data, error: null } : { ...prev, error }));
  });
  usePoll(client, tick, c => c.insights(14), 60000, ({ ok, data }) => {
    if (ok) setInsights(data);
  });
  usePoll(client, tick, c => c.settings(), 30000, ({ ok, data }) => {
    if (ok) setSettings(data);
  });

  // Run an action on the client, then refresh everything so the UI shows the result at once.
  const act = useCallback(async fn => {
    try {
      const res = await fn(client);
      refresh();
      return res;
    } catch (e) {
      return { ok: false, error: 'network', detail: String(e.message || e) };
    }
  }, [client, refresh]);

  const saveSettings = useCallback(async patch => {
    setSettings(prev => (prev ? { ...prev, settings: mergeLocal(prev.settings, patch) } : prev)); // optimistic
    const res = await act(c => c.saveSettings(patch));
    if (res.ok) setSettings({ settings: res.settings, effective: res.effective, timezone: res.timezone ?? settings?.timezone });
    return res;
  }, [act, settings?.timezone]);

  const value = useMemo(() => ({
    ready: !!client,
    client,
    source,
    isDemo: source === 'demo',
    chooseSource,
    refresh,
    act,
    pi,
    smoke,
    events,
    insights,
    settings,
    saveSettings,
  }), [client, source, chooseSource, refresh, act, pi, smoke, events, insights, settings, saveSettings]);

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

function mergeLocal(base, patch) {
  const out = { ...base };
  Object.entries(patch).forEach(([k, v]) => {
    out[k] = v && typeof v === 'object' && !Array.isArray(v) && base?.[k] && typeof base[k] === 'object' ? mergeLocal(base[k], v) : v;
  });
  return out;
}

export function useData() {
  const v = useContext(DataContext);
  if (!v) throw new Error('useData outside DataProvider');
  return v;
}

/** Seconds on the Pi's clock "right now", corrected for time since the last poll. */
export function useServerNow(intervalMs = 1000) {
  const { pi } = useData();
  const [wall, setWall] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setWall(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  const st = pi.status;
  return st && pi.at ? st.server_time + (wall - pi.at) / 1000 : wall / 1000;
}
