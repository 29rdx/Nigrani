import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ACCENTS, accentOf, cleanAccent, cleanMode, fromQuery, resolveMode } from './appearance.js';

test('unknown accents and modes fall back to the defaults instead of breaking the page', () => {
  assert.equal(cleanAccent('ember'), 'ember');
  assert.equal(cleanAccent('<script>'), 'violet');
  assert.equal(cleanAccent(null), 'violet');
  assert.equal(cleanMode('dark'), 'dark');
  assert.equal(cleanMode('blue'), '');
  assert.equal(accentOf('nope').id, 'violet');
});

test('"System" follows the system and an explicit mode wins', () => {
  assert.equal(resolveMode('', true), 'dark');
  assert.equal(resolveMode('', false), 'light');
  assert.equal(resolveMode('light', true), 'light');
  assert.equal(resolveMode('dark', false), 'dark');
});

test('a look can be previewed from the address', () => {
  assert.deepEqual(fromQuery('?accent=rose&theme=light'), { accent: 'rose', mode: 'light' });
  assert.deepEqual(fromQuery('?accent=x&theme=y'), { accent: null, mode: null });
  assert.deepEqual(fromQuery(''), { accent: null, mode: null });
});

test('every accent has a swatch and two logo colours', () => {
  ACCENTS.forEach((a) => { assert.match(a.swatch, /^#[0-9a-f]{6}$/i); assert.equal(a.logo.length, 2); });
  assert.equal(new Set(ACCENTS.map((a) => a.id)).size, ACCENTS.length);
});
