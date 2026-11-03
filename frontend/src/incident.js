import { fmtDuration } from './format.js';

const fmtClockShort = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

/** Merge everything known about an incident into one chronological list. `minor` items are the quiet ones. */
export function buildTimeline({ events = [], deploys = [], restarts = [], related = [] }) {
  const items = [];
  for (const e of events) {
    const base = { ts: e.ts, kind: e.kind, detail: e.detail };
    switch (e.kind) {
      case 'firing': items.push({ ...base, title: 'Alert fired', tone: 'crit' }); break;
      case 'severity': items.push({ ...base, title: 'Severity changed', tone: 'warn' }); break;
      case 'acknowledged': items.push({ ...base, title: 'Acknowledged', tone: 'info' }); break;
      case 'unacknowledged': items.push({ ...base, title: 'Acknowledgement ended', tone: 'info' }); break;
      case 'resolved': items.push({ ...base, title: 'Resolved', tone: 'ok' }); break;
      case 'suppressed': items.push({ ...base, title: 'Message suppressed', tone: '', minor: true }); break;
      default: items.push({ ...base, title: 'Notification', tone: '', minor: true });
    }
  }
  for (const d of deploys) {
    items.push({ ts: d.finished_at, kind: 'deploy', title: d.source === 'argocd' ? `Argo CD ${d.conclusion === 'success' ? 'synced' : 'sync failed:'} ${d.name} ${d.sha}` : `Deploy ${d.sha} ${d.conclusion || d.status}`, detail: d.source === 'argocd' ? 'Argo CD' : `${d.name}${d.actor ? ` by ${d.actor}` : ''}`, tone: d.conclusion === 'success' ? 'info' : 'warn', url: d.url });
  }
  // A crash loop is dozens of restarts: show each container's restarts as one line instead of burying the timeline.
  const byContainer = new Map();
  for (const r of restarts) byContainer.set(r.container, [...(byContainer.get(r.container) || []), r]);
  for (const [container, list] of byContainer) {
    if (list.length > 3) {
      const first = list[0], last = list[list.length - 1];
      items.push({ ts: first.ts, kind: 'restart', title: `${container} restarted ${list.length} times`,
        detail: `${first.count ? `restart #${first.count} to #${last.count}, ` : ''}between ${fmtClockShort(first.ts)} and ${fmtClockShort(last.ts)} (${fmtDuration(last.ts - first.ts)})`, tone: 'warn' });
    } else {
      for (const r of list) items.push({ ts: r.ts, kind: 'restart', title: r.count ? `${r.container} restarted` : `${r.container} started`, detail: r.count ? `restart #${r.count}` : 'container (re)started', tone: 'warn' });
    }
  }
  for (const r of related) {
    items.push({ ts: r.started_at, kind: 'related', title: `Also fired: ${r.rule_name}${r.series ? ` · ${r.series}` : ''}`, detail: r.status, tone: '', incident: r.id });
  }
  return items.sort((a, b) => a.ts - b.ts);
}

/** "What changed?" callouts: deploys and restarts shortly BEFORE the alert, and alerts that started alongside it. */
export function whatChanged({ incident, deploys = [], restarts = [], related = [] }, lookbackSeconds = 3600) {
  const t0 = incident.started_at;
  const out = [];
  const before = (list, key) => list.filter((x) => x[key] <= t0 + 60 && t0 - x[key] <= lookbackSeconds).sort((a, b) => b[key] - a[key]);
  const deploy = before(deploys, 'finished_at')[0];
  if (deploy) {
    const what = deploy.source === 'argocd' ? `Argo CD ${deploy.conclusion === 'success' ? 'synced' : 'failed to sync'} ${deploy.name} (${deploy.sha})` : `Deploy ${deploy.sha} (${deploy.conclusion || deploy.status})`;
    out.push({ tone: 'warn', text: `${what} ${deploy.source === 'argocd' ? '' : 'finished '}${fmtDuration(Math.max(0, t0 - deploy.finished_at))} before this alert started.`.replace('  ', ' ') });
  }
  const own = incident.labels && (incident.labels.name || incident.labels.container);
  const recent = before(restarts, 'ts');
  const ownRestarts = recent.filter((r) => r.container === own);
  if (ownRestarts.length >= 3) {
    out.push({ tone: 'crit', text: `${own} restarted ${ownRestarts.length} times in the hour before this alert started: it looks like a crash loop.` });
  } else {
    const restart = recent.find((r) => !own || r.container === own) || recent[0];
    if (restart) out.push({ tone: 'warn', text: `${restart.container} (re)started ${fmtDuration(Math.max(0, t0 - restart.ts))} before this alert started.` });
  }
  const around = related.filter((r) => Math.abs(r.started_at - t0) <= 900);
  if (around.length) out.push({ tone: 'info', text: `${around.length} other alert${around.length === 1 ? '' : 's'} started within 15 minutes: ${around.slice(0, 3).map((r) => r.rule_name).join(', ')}${around.length > 3 ? '…' : ''}.` });
  if (!out.length) out.push({ tone: 'ok', text: 'No deploy, restart or related alert in the hour before it started.' });
  return out;
}
