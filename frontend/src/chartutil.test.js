import assert from 'node:assert/strict';
import { test } from 'node:test';
import { escapeHtml, isFullRange, niceCeil, yRange } from './chartutil.js';

test('names from monitored systems cannot inject markup into a tooltip', () => {
  assert.equal(escapeHtml('<img src=x onerror=alert(1)>'), '&lt;img src=x onerror=alert(1)&gt;');
  assert.equal(escapeHtml(`a "b" & 'c'`), 'a &quot;b&quot; &amp; &#39;c&#39;');
  assert.equal(escapeHtml(42), '42');
});

test('round numbers', () => {
  assert.equal(niceCeil(7.3), 10);
  assert.equal(niceCeil(0.031), 0.05);
  assert.equal(niceCeil(72), 100);
  assert.equal(niceCeil(2.2), 2.5);
  assert.equal(niceCeil(0), 1);
});

test('a small percentage is readable, a big one is capped at 100, a CPU over 100 is not clipped', () => {
  assert.deepEqual(yRange('percent', 0, 6.1), [0, 10]);
  assert.deepEqual(yRange('percent', 0, 60), [0, 100]);
  assert.deepEqual(yRange('percent', 0, 97), [0, 100]);
  assert.equal(yRange('percent', 0, 230)[1], 230 * 1.15);
});

test('ratios stay within 0-1 unless the data does not', () => {
  assert.deepEqual(yRange('ratio', 0, 0.03), [0, 0.05]);
  assert.deepEqual(yRange('ratio', 0, 0.93), [0, 1]);
  assert.equal(yRange('ratio', 0, 3)[1], 3 * 1.15);
});

test('other units get headroom, and empty or negative data still gives a usable axis', () => {
  assert.ok(Math.abs(yRange('bytes', 0, 100)[1] - 115) < 1e-9);
  assert.deepEqual(yRange('short', 0, 0), [0, 1]);
  assert.equal(yRange('short', -5, 10)[0], -5);
});

test('zoom detection', () => {
  assert.equal(isFullRange(10, 100, 10, 100), true);
  assert.equal(isFullRange(20, 100, 10, 100), false);
  assert.equal(isFullRange(10, 80, 10, 100), false);
});
