import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildTimeline, whatChanged } from './incident.js';

const inc = { started_at: 10_000, labels: { name: 'api' } };

test('timeline merges lifecycle, deploys, restarts and related alerts in time order', () => {
  const items = buildTimeline({
    events: [{ ts: 10_000, kind: 'firing', detail: 'critical: 95%' }, { ts: 10_001, kind: 'notified', detail: 'firing: sent to 1 of 1 channel' }, { ts: 10_500, kind: 'resolved', detail: 'back to 5%' }],
    deploys: [{ finished_at: 9_700, sha: 'abc1234', conclusion: 'success', name: 'Deploy', actor: 'dev', url: 'u' }],
    restarts: [{ ts: 9_900, container: 'api' }],
    related: [{ started_at: 10_100, rule_name: 'Disk', series: '/', status: 'firing', id: 7 }],
  });
  assert.deepEqual(items.map((i) => i.kind), ['deploy', 'restart', 'firing', 'notified', 'related', 'resolved']);
  assert.equal(items.find((i) => i.kind === 'notified').minor, true);
  assert.equal(items.find((i) => i.kind === 'related').incident, 7);
  assert.equal(items[0].title, 'Deploy abc1234 success');
});

test('what changed points at the deploy and restart just before the alert', () => {
  const out = whatChanged({
    incident: inc,
    deploys: [{ finished_at: 9_760, sha: 'abc1234', conclusion: 'success' }, { finished_at: 2_000, sha: 'old', conclusion: 'success' }],
    restarts: [{ ts: 9_880, container: 'db' }, { ts: 9_900, container: 'api' }],
    related: [{ started_at: 10_300, rule_name: 'Disk full' }],
  });
  assert.match(out[0].text, /Deploy abc1234 \(success\) finished 4m before/);
  assert.match(out[1].text, /^api \(re\)started 1m before/);       // prefers the incident's own container
  assert.match(out[2].text, /1 other alert started within 15 minutes: Disk full/);
});

test('what changed says so when nothing preceded the alert', () => {
  const out = whatChanged({ incident: inc, deploys: [{ finished_at: 100, sha: 'x', conclusion: 'success' }], restarts: [], related: [] });
  assert.equal(out.length, 1);
  assert.equal(out[0].tone, 'ok');
});

test('a deploy that finished after the alert started is not blamed', () => {
  const out = whatChanged({ incident: inc, deploys: [{ finished_at: 10_500, sha: 'later', conclusion: 'success' }] });
  assert.ok(!out.some((o) => /later/.test(o.text)));
});

test('a crash loop is one timeline line, and what-changed calls it a crash loop', () => {
  const restarts = Array.from({ length: 12 }, (_, n) => ({ ts: 9_000 + n * 60, container: 'api', count: String(30 + n) }));
  const items = buildTimeline({ events: [{ ts: 10_000, kind: 'firing', detail: 'x' }], restarts: [...restarts, { ts: 9_950, container: 'db' }] });
  const loop = items.filter((i) => i.kind === 'restart');
  assert.equal(loop.length, 2);                                   // api grouped, db alone
  assert.equal(loop[0].title, 'api restarted 12 times');
  assert.match(loop[0].detail, /restart #30 to #41/);
  assert.equal(loop[1].title, 'db started');
  const out = whatChanged({ incident: inc, restarts });
  assert.equal(out[0].tone, 'crit');
  assert.match(out[0].text, /api restarted 12 times in the hour before this alert started: it looks like a crash loop/);
});

test('Argo CD syncs read as syncs, not as generic deploys', () => {
  const deploys = [{ source: 'argocd', name: 'web', sha: 'cafe123', conclusion: 'success', finished_at: 940 }];
  const timeline = buildTimeline({ deploys });
  assert.equal(timeline[0].title, 'Argo CD synced web cafe123');
  const w = whatChanged({ incident: { started_at: 1000, labels: {} }, deploys });
  assert.match(w[0].text, /^Argo CD synced web \(cafe123\) 1m before this alert started\.$/);
});
