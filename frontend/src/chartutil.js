// Pure helpers for charts (tested in chartutil.test.js).

/** Series names and labels come from monitored systems: never put them into HTML unescaped. */
export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** The next "round" number at or above x: 1, 2, 2.5, 5, 10 times a power of ten. */
export function niceCeil(x) {
  if (!(x > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(x));
  const f = x / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}

/**
 * The y range of a chart. Percentages and ratios fit what is plotted (a 6% error rate is readable, not a flat line at the bottom
 * of 0-100) but never claim more than 100% / 1.0 unless the data does. `max` already includes any threshold lines.
 */
export function yRange(unit, min, max) {
  const lo = Math.min(0, min);
  if (!(max > 0)) return [lo, 1];
  if (unit === 'percent') return [lo, max > 100 ? max * 1.15 : Math.min(100, Math.max(10, niceCeil(max * 1.2)))];
  if (unit === 'ratio') return [lo, max > 1 ? max * 1.15 : Math.min(1, niceCeil(max * 1.2))];
  return [lo, max * 1.15];
}

/** True when the zoomed x range [min, max] is the whole data range (nothing is zoomed). */
export function isFullRange(min, max, first, last) {
  return min <= first && max >= last;
}
