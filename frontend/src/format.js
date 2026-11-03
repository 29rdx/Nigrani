export function fmtBytes(n) {
  if (n == null) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  n = Number(n);
  while (Math.abs(n) >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${i === 0 ? n.toFixed(0) : n.toFixed(1)} ${u[i]}`;
}

export function fmtDuration(s) {
  if (s == null) return '—';
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

export function fmtValue(v, unit = 'short') {
  if (v == null || Number.isNaN(v)) return '—';
  switch (unit) {
    case 'ratio': return `${(v * 100).toFixed(1)}%`;
    case 'percent': return `${v.toFixed(1)}%`;
    case 'bytes': return fmtBytes(v);
    case 'bps': return `${fmtBytes(v)}/s`;
    case 'seconds': return Math.abs(v) < 1 ? `${(v * 1000).toFixed(0)} ms` : `${v.toFixed(2)} s`;
    case 'ms': return `${v.toFixed(0)} ms`;
    case 'days': return `${v.toFixed(1)} d`;
    case 'rps': return v >= 100 ? `${v.toFixed(0)}/s` : `${v.toFixed(2)}/s`;
    default: return Math.abs(v) >= 1000 ? Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(v)
      : Number.isInteger(v) ? String(v) : v.toFixed(2);
  }
}

export const fmtClock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
export const fmtDateTime = (ts) => new Date(ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
export const fmtAgo = (ts) => (ts ? `${fmtDuration(Date.now() / 1000 - ts)} ago` : '—');

export const SEV = {
  critical: { cls: 'crit', label: 'Critical' },
  warning: { cls: 'warn', label: 'Warning' },
  crit: { cls: 'crit', label: 'Critical' },
  warn: { cls: 'warn', label: 'Warning' },
  ok: { cls: 'ok', label: 'OK' },
  nodata: { cls: '', label: 'No data' },
};

export function lsGet(key, fallback) {
  try { const v = localStorage.getItem(key); return v == null ? fallback : v; } catch { return fallback; }
}
export function lsSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage may be blocked */ }
}

/** Status page day bar: green all good, amber a few failed checks, red a real outage, grey nothing recorded. */
export function dayClass(pct) {
  if (pct == null) return 'none';
  return pct >= 99.9 ? 'ok' : pct >= 99 ? 'warn' : 'bad';
}
