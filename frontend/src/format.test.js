import assert from 'node:assert/strict';
import { test } from 'node:test';
import { dayClass, fmtValue } from './format.js';

test('ratio values and thresholds display as percentages without clamping', () => {
  for (const [value, expected] of [[0, '0.0%'], [0.125, '12.5%'], [0.8, '80.0%'], [1, '100.0%'], [1.25, '125.0%'], [-0.25, '-25.0%']]) {
    assert.equal(fmtValue(value, 'ratio'), expected);
  }
});

test('missing ratios and existing percent values retain their formatting', () => {
  assert.equal(fmtValue(null, 'ratio'), '—');
  assert.equal(fmtValue(undefined, 'ratio'), '—');
  assert.equal(fmtValue(NaN, 'ratio'), '—');
  assert.equal(fmtValue(12.5, 'percent'), '12.5%');
  assert.equal(fmtValue(0.125), '0.13');
});

test('status page day bars', () => {
  assert.equal(dayClass(null), 'none');
  assert.equal(dayClass(100), 'ok');
  assert.equal(dayClass(99.9), 'ok');
  assert.equal(dayClass(99.5), 'warn');
  assert.equal(dayClass(97), 'bad');
  assert.equal(dayClass(0), 'bad');
});
