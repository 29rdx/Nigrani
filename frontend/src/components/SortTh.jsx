import { useCallback, useState } from 'react';
import { nextSort, sortRows } from '../sort';

/** Sort state for a table: `sort.apply(rows)` gives the rows in order, `<SortTh>` headers change it. */
export function useSort(getters = {}, initial = { key: null, dir: 'asc' }) {
  const [s, setS] = useState(initial);
  const toggle = useCallback((k) => setS((p) => nextSort(p, k)), []);
  const apply = useCallback((rows) => sortRows(rows, s.key, s.dir, getters), [s.key, s.dir]); // eslint-disable-line react-hooks/exhaustive-deps
  return { ...s, toggle, apply };
}

export function SortTh({ label, k, sort }) {
  const on = sort.key === k;
  return (
    <th aria-sort={on ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="sort" onClick={() => sort.toggle(k)}>{label}<span aria-hidden="true">{on ? (sort.dir === 'asc' ? '↑' : '↓') : '↕'}</span></button>
    </th>
  );
}
