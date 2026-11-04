import assert from 'node:assert/strict';
import { test } from 'node:test';
import { faviconHref, pageTitle } from './brand.js';

test('the title carries the firing count', () => {
  assert.equal(pageTitle(0, 'Overview', 'Nigrani'), 'Overview · Nigrani');
  assert.equal(pageTitle(3, 'Alerts', 'Nigrani'), '(3) Alerts · Nigrani');
  assert.equal(pageTitle(250, 'Alerts', 'Nigrani'), '(99+) Alerts · Nigrani');
});

test('the favicon gets a red dot only while something fires', () => {
  assert.ok(faviconHref(0).startsWith('data:image/svg+xml,'));
  assert.ok(!decodeURIComponent(faviconHref(0)).includes('e5484d'));
  assert.ok(decodeURIComponent(faviconHref(2)).includes('e5484d'));
  assert.ok(decodeURIComponent(faviconHref(0, 'violet')).includes('#8f72ff'));         // the icon follows the accent
  assert.ok(decodeURIComponent(faviconHref(0, 'nonsense')).includes('#f5873a'));       // an unknown accent falls back to ember
});
