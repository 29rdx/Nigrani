import { useEffect, useMemo, useRef, useState } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import { escapeHtml, isFullRange, yRange } from '../chartutil';
import { useApp } from '../ctx';
import { fmtClock, fmtDateTime, fmtValue } from '../format';
import { Icon } from './ui';

const VARS = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];
const FONT = '11px "Inter Variable", system-ui, sans-serif';

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888';
}

/** Merge series with differing timestamps onto a shared x axis. */
export function align(series) {
  const set = new Set();
  series.forEach((s) => s.points.forEach((p) => set.add(p[0])));
  const xs = [...set].sort((a, b) => a - b);
  const idx = new Map(xs.map((x, i) => [x, i]));
  const ys = series.map((s) => {
    const a = new Array(xs.length).fill(null);
    s.points.forEach(([t, v]) => { a[idx.get(t)] = v; });
    return a;
  });
  return [xs, ...ys];
}

const NO_MARKERS = [];
const NO_THRESHOLDS = [];
const syncs = new Map();                      // charts that share a key share their crosshair and their zoom
const syncFor = (key) => { if (!syncs.has(key)) syncs.set(key, uPlot.sync(key)); return syncs.get(key); };

/**
 * A time series chart. Drag across it to zoom (double-click or "Reset zoom" to undo); hover a legend entry to
 * highlight that series, click it to hide or show it. Charts given the same `sync` move their crosshair together.
 */
export default function Chart({ series, unit = 'short', kind = 'line', height = 190, markers = NO_MARKERS, thresholds = NO_THRESHOLDS, theme, legend = true, sync, label }) {
  const { look } = useApp();                    // changes with the theme and the accent, so the lines are redrawn in the new colours
  const host = useRef(null);
  const tip = useRef(null);
  const plot = useRef(null);
  const zoom = useRef(null);                    // {min, max} while zoomed; survives the periodic data refresh
  const hidden = useRef(new Set());             // series the person switched off
  const [zoomed, setZoomed] = useState(false);
  const [, repaint] = useState(0);
  const data = useMemo(() => align(series), [series]);
  const hasData = series.length > 0 && data[0].length > 0;

  useEffect(() => {
    if (!hasData || !host.current) return undefined;
    const el = host.current;
    const colors = series.map((_, i) => cssVar(VARS[i % VARS.length]));
    const grid = cssVar('--border'); const text = cssVar('--muted');
    const axis = (extra) => ({ stroke: text, grid: { stroke: grid, width: 1 }, ticks: { show: false }, font: FONT, ...extra });
    let applying = false;
    const opts = {
      width: el.clientWidth, height, padding: [8, 22, 0, 0],
      cursor: { points: { size: 6 }, drag: { x: true, y: false, setScale: true }, sync: sync ? { key: syncFor(sync).key } : undefined },
      legend: { show: false },
      focus: { alpha: 0.3 },
      scales: {
        x: { time: true },
        y: { range: (_u, min, max) => yRange(unit, min, Math.max(max, ...thresholds.map((t) => t.value))) },
      },
      axes: [
        axis({ values: (_u, v) => v.map((t) => fmtClock(t)) }),
        axis({ size: 62, values: (_u, v) => v.map((x) => fmtValue(x, unit)) }),
      ],
      series: [{}, ...series.map((s, i) => ({
        label: s.name, stroke: colors[i], width: 1.6, points: { show: false }, spanGaps: false,
        fill: kind === 'area' ? (u) => {
          const g = u.ctx.createLinearGradient(0, u.bbox.top, 0, u.bbox.top + u.bbox.height);
          g.addColorStop(0, `${colors[i]}44`); g.addColorStop(1, `${colors[i]}05`);
          return g;
        } : undefined,
      }))],
      hooks: {
        setScale: [(u, key) => {
          if (key !== 'x' || applying) return;
          const { min, max } = u.scales.x;
          const xs = u.data[0];
          const full = isFullRange(min, max, xs[0], xs[xs.length - 1]);
          zoom.current = full ? null : { min, max };
          setZoomed(!full);
        }],
        draw: [(u) => {
          const { ctx, bbox } = u;
          thresholds.forEach((t) => {
            const y = Math.round(u.valToPos(t.value, 'y', true));
            if (y < bbox.top || y > bbox.top + bbox.height) return;
            ctx.save();
            ctx.strokeStyle = t.color; ctx.fillStyle = t.color; ctx.globalAlpha = 0.85; ctx.setLineDash([2, 4]); ctx.lineWidth = 1.5;
            ctx.beginPath(); ctx.moveTo(bbox.left, y); ctx.lineTo(bbox.left + bbox.width, y); ctx.stroke();
            ctx.setLineDash([]); ctx.font = `${11 * devicePixelRatio}px "Inter Variable", system-ui, sans-serif`; ctx.textAlign = 'right';
            ctx.fillText(t.label, bbox.left + bbox.width - 4, y - 5 * devicePixelRatio);
            ctx.restore();
          });
          markers.forEach((m) => {
            const x = Math.round(u.valToPos(m.ts, 'x', true));
            if (x < bbox.left || x > bbox.left + bbox.width) return;
            ctx.save();
            ctx.strokeStyle = m.color || cssVar('--accent'); ctx.globalAlpha = 0.8;
            ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5;
            ctx.beginPath(); ctx.moveTo(x, bbox.top); ctx.lineTo(x, bbox.top + bbox.height); ctx.stroke();
            ctx.restore();
          });
        }],
        setCursor: [(u) => {
          const t = tip.current; if (!t) return;
          const i = u.cursor.idx;
          if (i == null || u.cursor.left < 0) { t.style.display = 'none'; return; }
          const rows = series.map((s, k) => (hidden.current.has(k) ? '' : `<div class="r"><i style="background:${colors[k]}"></i>${escapeHtml(s.name)}: <b>${escapeHtml(fmtValue(u.data[k + 1][i], unit))}</b></div>`)).join('');
          const step = u.data[0].length > 1 ? u.data[0][1] - u.data[0][0] : 0;
          const near = markers.find((m) => Math.abs(m.ts - u.data[0][i]) < step * 1.5);
          t.innerHTML = `<div class="tt">${escapeHtml(fmtDateTime(u.data[0][i]))}</div>${rows}${near ? `<div class="tt">▸ ${escapeHtml(near.label)}</div>` : ''}`;
          t.style.display = 'block';
          const left = u.cursor.left + 14; const w = t.offsetWidth;
          t.style.left = `${left + w > el.clientWidth ? u.cursor.left - w - 14 : left}px`;
          t.style.top = `${Math.max(0, u.cursor.top - 10)}px`;
        }],
      },
    };
    const u = new uPlot(opts, data, el);
    plot.current = u;
    applying = true;                              // put back what the person had: the zoom and the hidden series
    if (zoom.current) u.setScale('x', zoom.current);
    hidden.current.forEach((i) => { if (i < series.length) u.setSeries(i + 1, { show: false }); });
    applying = false;
    const ro = new ResizeObserver(() => u.setSize({ width: el.clientWidth, height }));
    ro.observe(el);
    return () => { ro.disconnect(); u.destroy(); plot.current = null; };
  }, [data, series, unit, kind, height, markers, thresholds, theme, look, hasData, sync]);

  if (!hasData) {
    return <div className="empty chart-empty"><Icon name="chart" size={20} /><div>No data in this range.</div></div>;
  }
  const last = (s) => { for (let i = s.points.length - 1; i >= 0; i--) if (s.points[i][1] != null) return s.points[i][1]; return null; };
  const resetZoom = () => {
    zoom.current = null; setZoomed(false);
    const own = plot.current;
    const all = sync ? [...new Set([own, ...syncFor(sync).plots])] : [own];            // charts that zoom together reset together
    all.filter(Boolean).forEach((u) => { const xs = u.data[0]; u.setScale('x', { min: xs[0], max: xs[xs.length - 1] }); });
  };
  const toggle = (i) => {
    if (hidden.current.has(i)) hidden.current.delete(i); else hidden.current.add(i);
    plot.current?.setSeries(i + 1, { show: !hidden.current.has(i) });
    repaint((n) => n + 1);
  };
  const summary = `${label || 'Chart'}: ${series.slice(0, 4).map((s) => `${s.name} ${fmtValue(last(s), unit)}`).join(', ')}`;
  return (
    <div>
      <div className="chart" style={{ position: 'relative' }}>
        <div ref={host} role="img" aria-label={summary} />
        <div ref={tip} className="tip" />
        {zoomed && <button className="btn sm chart-reset" onClick={resetZoom}><Icon name="refresh" size={13} />Reset zoom</button>}
      </div>
      {legend && series.length > 0 && (
        <div className="legend">
          {series.map((s, i) => (
            <button key={s.name + i} type="button" className={hidden.current.has(i) ? 'off' : ''} aria-pressed={!hidden.current.has(i)}
              title={hidden.current.has(i) ? 'Show this series' : 'Click to hide; hover to highlight'}
              onMouseEnter={() => plot.current?.setSeries(i + 1, { focus: true }, false)} onMouseLeave={() => plot.current?.setSeries(null, { focus: true }, false)}
              onFocus={() => plot.current?.setSeries(i + 1, { focus: true }, false)} onBlur={() => plot.current?.setSeries(null, { focus: true }, false)}
              onClick={() => toggle(i)}>
              <i style={{ background: `var(${VARS[i % VARS.length]})` }} />{s.name}<b>{fmtValue(last(s), unit)}</b>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
