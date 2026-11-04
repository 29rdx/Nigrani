import assert from 'node:assert/strict';
import { test } from 'node:test';
import { compareValues, nextSort, sortRows } from './sort.js';

test('numbers sort numerically and names naturally', () => {
  assert.ok(compareValues(9, 10) < 0);
  assert.ok(compareValues('pod-2', 'pod-10') < 0);
  assert.ok(compareValues('Api', 'nginx') < 0);
});

test('sorting by a column, ascending and descending, is stable and keeps empty values last either way', () => {
  const rows = [{ n: 'b', v: 5 }, { n: 'a', v: null }, { n: 'c', v: 1 }, { n: 'd', v: 5 }, { n: 'e', v: undefined }];
  assert.deepEqual(sortRows(rows, 'v', 'asc').map((r) => r.n), ['c', 'b', 'd', 'a', 'e']);
  assert.deepEqual(sortRows(rows, 'v', 'desc').map((r) => r.n), ['b', 'd', 'c', 'a', 'e']);
  assert.equal(sortRows(rows, null, 'asc'), rows);                       // no column: untouched
});

test('a getter can sort by something computed', () => {
  const rows = [{ s: 'warning' }, { s: 'critical' }, { s: 'info' }];
  const rank = { critical: 0, warning: 1, info: 2 };
  assert.deepEqual(sortRows(rows, 'sev', 'asc', { sev: (r) => rank[r.s] }).map((r) => r.s), ['critical', 'warning', 'info']);
});

test('pressing a header: a new column ascends, the same column flips', () => {
  assert.deepEqual(nextSort({ key: null, dir: 'asc' }, 'cpu'), { key: 'cpu', dir: 'asc' });
  assert.deepEqual(nextSort({ key: 'cpu', dir: 'asc' }, 'cpu'), { key: 'cpu', dir: 'desc' });
  assert.deepEqual(nextSort({ key: 'cpu', dir: 'desc' }, 'mem'), { key: 'mem', dir: 'asc' });
});
