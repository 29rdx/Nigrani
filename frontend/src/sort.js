// Column sorting for tables (pure; tested in sort.test.js).

/** Numbers numerically, text naturally ("pod-2" before "pod-10"), empty values last. */
export function compareValues(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

const isEmpty = (v) => v == null || v === '' || (typeof v === 'number' && Number.isNaN(v));

/** Stable sort of `rows` by `key` (or by `getters[key](row)`); empty values stay at the end in either direction. */
export function sortRows(rows, key, dir = 'asc', getters = {}) {
  if (!key) return rows;
  const get = getters[key] || ((r) => r[key]);
  const sign = dir === 'desc' ? -1 : 1;
  return rows.map((r, i) => [r, i, get(r)]).sort((x, y) => {
    const ex = isEmpty(x[2]); const ey = isEmpty(y[2]);
    if (ex || ey) return ex === ey ? x[1] - y[1] : ex ? 1 : -1;
    return compareValues(x[2], y[2]) * sign || x[1] - y[1];
  }).map((x) => x[0]);
}

/** The next sort state when a column header is pressed: a new column starts ascending, the same one flips. */
export function nextSort(current, key) {
  return current.key === key ? { key, dir: current.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' };
}

export const SEVERITY_RANK = { critical: 0, warning: 1, info: 2 };
