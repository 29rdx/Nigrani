import { useEffect, useRef } from 'react';
import { SEV } from '../format';

const PATHS = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M14 14h7v7h-7z M3 14h7v7H3z',
  box: 'M21 8l-9-5-9 5v8l9 5 9-5V8z M3.3 7.5L12 12.5l8.7-5 M12 22V12.5',
  server: 'M4 4h16v6H4z M4 14h16v6H4z M8 7h.01 M8 17h.01',
  activity: 'M22 12h-4l-3 9L9 3l-3 9H2',
  database: 'M12 3c4.4 0 8 1.1 8 2.5S16.4 8 12 8 4 6.9 4 5.5 7.6 3 12 3z M4 5.5v13C4 19.9 7.6 21 12 21s8-1.1 8-2.5v-13 M4 12c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5',
  radio: 'M12 12h.01 M16.2 7.8a6 6 0 010 8.4 M7.8 16.2a6 6 0 010-8.4 M19 5a10 10 0 010 14 M5 19a10 10 0 010-14',
  pulse: 'M3 12h4l3-8 4 16 3-8h4',
  layers: 'M12 2L2 7l10 5 10-5-10-5z M2 17l10 5 10-5 M2 12l10 5 10-5',
  chart: 'M3 3v18h18 M7 14l4-4 3 3 5-6',
  file: 'M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z M14 2v6h6 M8 13h8 M8 17h8',
  bell: 'M18 8a6 6 0 00-12 0c0 7-3 9-3 9h18s-3-2-3-9 M13.7 21a2 2 0 01-3.4 0',
  plug: 'M12 22v-5 M9 8V2 M15 8V2 M18 8v5a6 6 0 01-12 0V8z',
  rocket: 'M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2.1-.1-2.9a2.2 2.2 0 00-2.9-.1z M12 15l-3-3a22 22 0 012-4 12.9 12.9 0 0111-6c0 2.7-.8 7.5-6 11a22 22 0 01-4 2z M9 12H4s.6-3 2-4c1.6-1.1 5 0 5 0 M12 15v5s3-.6 4-2c1.1-1.6 0-5 0-5',
  shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
  sun: 'M12 8a4 4 0 100 8 4 4 0 000-8z M12 1v2 M12 21v2 M4.2 4.2l1.4 1.4 M18.4 18.4l1.4 1.4 M1 12h2 M21 12h2 M4.2 19.8l1.4-1.4 M18.4 5.6l1.4-1.4',
  moon: 'M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z',
  x: 'M18 6L6 18 M6 6l12 12',
  plus: 'M12 5v14 M5 12h14',
  check: 'M20 6L9 17l-5-5',
  alert: 'M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z M12 9v4 M12 17h.01',
  logout: 'M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4 M16 17l5-5-5-5 M21 12H9',
  menu: 'M3 12h18 M3 6h18 M3 18h18',
  refresh: 'M23 4v6h-6 M1 20v-6h6 M3.5 9a9 9 0 0114.9-3.4L23 10 M1 14l4.6 4.4A9 9 0 0020.5 15',
  edit: 'M12 20h9 M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z',
  trash: 'M3 6h18 M8 6V4h8v2 M19 6l-1 14H6L5 6',
  download: 'M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4 M7 10l5 5 5-5 M12 15V3',
  upload: 'M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4 M17 8l-5-5-5 5 M12 3v12',
  users: 'M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2 M9 11a4 4 0 100-8 4 4 0 000 8z M23 21v-2a4 4 0 00-3-3.9 M16 3.1a4 4 0 010 7.8',
  layers: 'M12 2l10 5-10 5L2 7l10-5z M2 17l10 5 10-5 M2 12l10 5 10-5',
  bug: 'M8 2l1.88 1.88 M14.12 3.88L16 2 M9 7.13v-1a3.003 3.003 0 116 0v1 M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 014-4h4a4 4 0 014 4v3c0 3.3-2.7 6-6 6 M12 20v-9 M6.53 9C4.6 8.8 3 7.1 3 5 M6 13H2 M3 21c0-2.1 1.7-3.9 3.8-4 M20.97 5c0 2.1-1.6 3.8-3.5 4 M22 13h-4 M17.2 17c2.1.1 3.8 1.9 3.8 4',
  search: 'M11 19a8 8 0 100-16 8 8 0 000 16z M21 21l-4.3-4.3',
  sparkle: 'M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15z',
  external: 'M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6 M15 3h6v6 M10 14L21 3',
};

export function Icon({ name, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name] || PATHS.chart} />
    </svg>
  );
}

export function Badge({ kind = '', children, icon }) {
  return <span className={`badge ${kind}`}>{icon && <Icon name={icon} size={12} />}{children}</span>;
}

/** Severity/status badge. Always shows text + shape, never colour alone. */
export function SevBadge({ sev }) {
  const s = SEV[sev] || SEV.nodata;
  return <Badge kind={s.cls} icon={s.cls === 'crit' ? 'alert' : s.cls === 'warn' ? 'alert' : s.cls === 'ok' ? 'check' : undefined}>{s.label}</Badge>;
}

export function Card({ title, sub, actions, children, flush, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="hd">
          <span>{title}</span>{sub && <span className="sub">{sub}</span>}
          <span className="right row">{actions}</span>
        </div>
      )}
      <div className={`bd ${flush ? 'flush' : ''}`}>{children}</div>
    </section>
  );
}

export function Empty({ title, children }) {
  return <div className="empty"><h2>{title}</h2><div>{children}</div></div>;
}

export function ErrorNote({ children }) {
  if (!children) return null;
  return <div className="err" role="alert">{children}</div>;
}

export function Toggle({ checked, onChange, label }) {
  return (
    <label className="toggle" title={label}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} aria-label={label} />
      <span />
    </label>
  );
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Keeps Tab inside the dialog, puts focus in it when it opens and back where it was when it closes. */
function useFocusTrap(onClose) {
  const ref = useRef(null);
  useEffect(() => {
    const before = document.activeElement;
    const el = ref.current;
    if (el && !el.contains(document.activeElement)) (el.querySelector('[autofocus], input, select, textarea') || el.querySelector(FOCUSABLE) || el).focus?.();
    const key = (e) => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'Tab' || !el) return;
      const nodes = [...el.querySelectorAll(FOCUSABLE)].filter((n) => n.offsetParent !== null);
      if (nodes.length === 0) { e.preventDefault(); return; }
      const first = nodes[0]; const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener('keydown', key);
    return () => { window.removeEventListener('keydown', key); if (before && before.focus) before.focus(); };
  }, [onClose]);
  return ref;
}

export function Modal({ title, onClose, children, actions }) {
  const ref = useFocusTrap(onClose);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={ref} tabIndex={-1}>
        <h2>{title}</h2>
        {children}
        {actions && <div className="actions">{actions}</div>}
      </div>
    </div>
  );
}

export function Drawer({ onClose, children }) {
  const ref = useFocusTrap(onClose);
  return (
    <div className="drawer-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="drawer" role="dialog" aria-modal="true" aria-label="Details" ref={ref} tabIndex={-1}>{children}</div>
    </div>
  );
}

export function Seg({ value, options, onChange }) {
  return (
    <div className="seg" role="group">
      {options.map((o) => (
        <button key={o} className={o === value ? 'on' : ''} onClick={() => onChange(o)} aria-pressed={o === value}>{o}</button>
      ))}
    </div>
  );
}

/** Inline sparkline. Points: [[ts, value|null], ...] */
export function Spark({ points, status }) {
  const pts = (points || []).filter((p) => p[1] != null);
  if (pts.length < 2) return <div className="spark" />;
  const xs = pts.map((p) => p[0]); const ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs); const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const W = 200, H = 28;
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${(((p[0] - x0) / (x1 - x0 || 1)) * W).toFixed(1)},${(H - 2 - ((p[1] - y0) / (y1 - y0 || 1)) * (H - 4)).toFixed(1)}`).join(' ');
  const color = status === 'crit' ? 'var(--crit)' : status === 'warn' ? 'var(--warn)' : 'var(--accent)';
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={path} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Progress bar with optional warn/crit markers (values in the same unit as `max`). */
export function Meter({ value, max = 100, warn, crit, status }) {
  const pct = (v) => `${Math.min(100, Math.max(0, (v / max) * 100))}%`;
  return (
    <div className="bar" role="img" aria-label={`${value} of ${max}`}>
      <div className={`fill ${status === 'crit' ? 'crit' : status === 'warn' ? 'warn' : status === 'nodata' ? 'unk' : ''}`}
        style={{ width: value == null ? 0 : pct(value) }} />
      {warn != null && <i className="mark warn" style={{ left: pct(warn) }} />}
      {crit != null && <i className="mark crit" style={{ left: pct(crit) }} />}
    </div>
  );
}
