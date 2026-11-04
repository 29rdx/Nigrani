import assert from 'node:assert/strict';
import { test } from 'node:test';
import { gotoRoute, isTyping, rank, score } from './palette.js';

test('exact beats prefix beats word start beats inside beats scattered letters', () => {
  const s = (q, t) => score(q, t);
  assert.ok(s('alerts', 'Alerts') > s('alert', 'Alerts'));
  assert.ok(s('con', 'Containers') > s('con', 'Kubernetes control'));
  assert.ok(s('disk', 'Host disk') > s('isk', 'Host disk'));
  assert.ok(s('isk', 'Host disk') > s('hdk', 'Host disk'));
  assert.equal(s('zzz', 'Containers'), -1);
  assert.ok(s('ctr', 'Containers') > 0);
});

test('an empty query keeps the order, a typed one ranks and drops non-matches', () => {
  const items = [{ label: 'Overview' }, { label: 'Containers' }, { label: 'Alerts' }, { label: 'Audit log', hint: 'who did what' }];
  assert.deepEqual(rank(items, '').map((i) => i.label), ['Overview', 'Containers', 'Alerts', 'Audit log']);
  assert.equal(rank(items, 'al')[0].label, 'Alerts');                  // the best match first (scattered matches follow)
  assert.deepEqual(rank(items, 'aud')[0].label, 'Audit log');
  assert.equal(rank(items, 'who')[0].label, 'Audit log');            // matches on the hint too
  assert.equal(rank(items, 'nothing like this').length, 0);
  assert.equal(rank(items, '', 2).length, 2);
});

test('go-to shortcuts and the typing guard', () => {
  assert.equal(gotoRoute('a'), '/alerts/active');
  assert.equal(gotoRoute('A'), '/alerts/active');
  assert.equal(gotoRoute('x'), null);
  assert.equal(isTyping({ tagName: 'INPUT' }), true);
  assert.equal(isTyping({ tagName: 'TEXTAREA' }), true);
  assert.equal(isTyping({ tagName: 'DIV', isContentEditable: true }), true);
  assert.equal(isTyping({ tagName: 'BUTTON' }), false);
  assert.equal(isTyping(null), false);
});
