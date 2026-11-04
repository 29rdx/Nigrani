import { useCallback, useEffect, useRef, useState } from 'react';
import { useApp } from './ctx';

let currentServer = '';
export function setCurrentServer(id) { currentServer = id; }

// Endpoints that read one server's Prometheus/Loki/checks. Everything else (rules, channels, incidents,
// silences, fleet...) is global and takes an explicit `server` filter where it makes sense.
const SCOPED = ['/overview', '/containers', '/host', '/pages', '/logs', '/deploys', '/checks', '/rules/test', '/grafana-links', '/sentry', '/kubernetes', '/datadog', '/discovery', '/argocd', '/slos'];
export function scoped(path, server = currentServer) {
  if (!server || !SCOPED.some((p) => path === p || path.startsWith(`${p}/`) || path.startsWith(`${p}?`))) return path;
  return `${path}${path.includes('?') ? '&' : '?'}server=${encodeURIComponent(server)}`;
}

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = 'GET', body, server } = {}) {
  const res = await fetch(`/api${scoped(path, server ?? currentServer)}`, {
    method,
    credentials: 'same-origin',
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), 'X-Requested-With': 'nigrani' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && !path.startsWith('/login') && !path.startsWith('/me') && !path.startsWith('/public')) {
    window.dispatchEvent(new Event('nigrani:unauth'));
  }
  if (res.status === 403) window.dispatchEvent(new Event('nigrani:forbidden'));   // maybe our role changed: refresh it
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const d = data && data.detail;
    throw new ApiError(res.status, typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join('; ') : res.statusText);
  }
  return data;
}

/** Fetch `path` and keep it fresh every `interval` ms. Re-fetches when path changes. */
export function useApi(path, { interval = 0, enabled = true } = {}) {
  const { server } = useApp();
  const [state, setState] = useState({ data: null, error: null, loading: enabled });
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!enabled || !path) return;
    const id = ++seq.current;
    try {
      const data = await api(path, { server });
      if (id === seq.current) setState({ data, error: null, loading: false });
    } catch (e) {
      if (id === seq.current) setState((s) => ({ data: s.data, error: e.message, loading: false }));
    }
  }, [path, enabled, server]);

  useEffect(() => {
    setState((s) => ({ ...s, loading: true }));
    load();
    if (!interval) return undefined;
    const t = setInterval(load, interval);
    return () => clearInterval(t);
  }, [load, interval]);

  return { ...state, reload: load };
}

export function useHashRoute() {
  const get = () => window.location.hash.replace(/^#/, '') || '/overview';
  const [route, setRoute] = useState(get);
  useEffect(() => {
    const on = () => setRoute(get());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return route;
}

/** True once Nigrani itself stops answering (two failed health checks in a row); announces recovery with an event. */
export function useConnectionLost() {
  const [lost, setLost] = useState(false);
  useEffect(() => {
    let fails = 0;
    const tick = async () => {
      try {
        const r = await fetch('/api/health', { cache: 'no-store' });
        if (!r.ok) throw new Error('unhealthy');
        if (fails >= 2) window.dispatchEvent(new Event('nigrani:reconnected'));
        fails = 0; setLost(false);
      } catch { fails += 1; if (fails >= 2) setLost(true); }
    };
    const t = setInterval(tick, 10000);
    window.addEventListener('online', tick);
    return () => { clearInterval(t); window.removeEventListener('online', tick); };
  }, []);
  return lost;
}
