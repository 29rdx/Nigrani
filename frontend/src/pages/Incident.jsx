import { useEffect, useMemo, useState } from 'react';
import { api, useApi } from '../api';
import Chart from '../components/Chart';
import { Badge, Card, Empty, ErrorNote, Icon, Seg, SevBadge } from '../components/ui';
import { useApp } from '../ctx';
import { fmtAgo, fmtClock, fmtDateTime, fmtDuration, fmtValue } from '../format';
import { buildTimeline, whatChanged } from '../incident';
import AiExplain from '../components/AiExplain';
import { ExploreButton } from '../components/Grafana';
import { AckModal } from './Alerts';
import { IssueTable } from './Sentry';

const ICON = { crit: 'alert', warn: 'alert', ok: 'check', info: 'activity', '': 'activity' };

function Header({ d, reload }) {
  const { servers, multi, can } = useApp();
  const i = d.incident;
  const [acking, setAcking] = useState(false);
  const firing = i.status === 'firing';
  const end = i.resolved_at || Date.now() / 1000;
  const unack = async () => { await api(`/incidents/${i.id}/ack`, { method: 'DELETE' }); reload(); };
  const silence = async () => { await api('/silences', { method: 'POST', body: { server: i.server, source_id: i.source_id, match: i.series || null, minutes: 60, reason: 'Silenced from the incident page' } }); reload(); };
  return (
    <Card>
      <div className="row wrap">
        <SevBadge sev={i.severity} />
        {firing ? <Badge kind="crit" icon="alert">Firing</Badge> : <Badge kind="ok" icon="check">Resolved after {fmtDuration(end - i.started_at)}</Badge>}
        {multi && <Badge kind="info">{servers.find((s) => s.id === i.server)?.name || i.server}</Badge>}
        {i.acked_at && <Badge kind="info" icon="check">acknowledged by {i.acked_by}</Badge>}
        {i.silenced && <Badge>silenced</Badge>}
        {firing && can.edit && (
          <span className="right row">
            {i.acked_at ? <button className="btn sm" onClick={unack}>Un-acknowledge</button> : <button className="btn sm" onClick={() => setAcking(true)}>Acknowledge</button>}
            <button className="btn sm" onClick={silence}>Silence 1h</button>
          </span>
        )}
      </div>
      <h2 style={{ margin: '12px 0 4px' }}>{i.rule_name}{i.series && <span className="muted"> · {i.series}</span>}</h2>
      {i.summary && <div className="muted">{i.summary}</div>}
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', marginTop: 14 }}>
        {[['Started', `${fmtDateTime(i.started_at)} (${fmtAgo(i.started_at)})`],
          [firing ? 'Going for' : 'Lasted', fmtDuration(end - i.started_at)],
          ['Latest value', fmtValue(i.last_value, i.unit)],
          ['Peak', fmtValue(i.peak_value, i.unit)],
          ['Threshold', fmtValue(i.threshold, i.unit)]].map(([k, v]) => (
            <div key={k}><div className="muted" style={{ fontSize: 12 }}>{k}</div><div style={{ fontWeight: 600 }}>{v}</div></div>
          ))}
      </div>
      {(d.grafana?.explore || d.grafana?.links?.length > 0) && (
        <div className="row wrap" style={{ marginTop: 12 }}>
          <span className="muted">Grafana:</span>
          <ExploreButton url={d.grafana.explore} label="Explore this query" />
          {d.grafana.links.map((l) => <ExploreButton key={l.title} url={l.url} label={l.title} />)}
        </div>
      )}
      {i.ack_note && <div className="notice" style={{ marginTop: 12 }}>“{i.ack_note}” <span className="muted">— {i.acked_by}</span></div>}
      {acking && <AckModal incident={i} onClose={() => setAcking(false)} onDone={() => { setAcking(false); reload(); }} />}
    </Card>
  );
}

function Changed({ d }) {
  const items = useMemo(() => whatChanged(d), [d]);
  return (
    <Card title="What changed?" sub="in the hour before it started">
      <div className="stack">
        {items.map((c, n) => (
          <div key={n} className="row" style={{ alignItems: 'flex-start' }}>
            <span style={{ color: `var(--${c.tone === 'warn' ? 'warn' : c.tone === 'ok' ? 'ok' : 'accent'})`, marginTop: 2 }}><Icon name={ICON[c.tone] || 'activity'} size={16} /></span>
            <span>{c.text}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Timeline({ d }) {
  const [all, setAll] = useState(false);
  const items = useMemo(() => buildTimeline(d), [d]);
  const shown = all ? items : items.filter((x) => !x.minor);
  return (
    <Card title="Timeline" actions={<label className="row" style={{ gap: 6, fontWeight: 400 }}><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show notifications</label>} flush>
      {shown.length === 0 ? <Empty title="No events recorded">Events are recorded from the moment an alert fires.</Empty> : (
        <div className="list">
          {shown.map((x, n) => (
            <div key={n} className="row" style={{ alignItems: 'flex-start', opacity: x.minor ? 0.75 : 1 }}>
              <span className="mono muted" style={{ width: 62, flex: 'none' }}>{fmtClock(x.ts)}</span>
              <span style={{ color: `var(--${x.tone === 'crit' ? 'crit' : x.tone === 'warn' ? 'warn' : x.tone === 'ok' ? 'ok' : x.tone === 'info' ? 'accent' : 'muted'})`, flex: 'none', marginTop: 2 }}><Icon name={ICON[x.tone] || 'activity'} size={15} /></span>
              <div style={{ minWidth: 0 }}>
                <b>{x.incident ? <a href={`#/incident/${x.incident}`}>{x.title}</a> : x.url ? <a href={x.url} target="_blank" rel="noreferrer noopener">{x.title}</a> : x.title}</b>
                {x.detail && <div className="muted" style={{ fontSize: 12.5 }}>{x.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function IncidentLogs({ d }) {
  const { me } = useApp();
  const i = d.incident;
  const container = i.labels?.container || i.labels?.name || '';
  const [level, setLevel] = useState('warn');
  const [state, setState] = useState({ rows: [], error: null, loading: true });
  const logsEnabled = me.servers.find((s) => s.id === i.server)?.logs;

  useEffect(() => {
    if (!logsEnabled || !container) return undefined;
    let alive = true;
    const p = new URLSearchParams({ container, start: d.window.start, end: d.window.end, limit: '150' });
    if (level !== 'all') p.set('level', level);
    api(`/logs?${p}`, { server: i.server })
      .then((r) => alive && setState({ rows: r.rows, error: null, loading: false }))
      .catch((e) => alive && setState({ rows: [], error: e.message, loading: false }));
    return () => { alive = false; };
  }, [container, level, d.window.start, d.window.end, i.server, logsEnabled]);

  if (!logsEnabled || !container) return null;
  const cls = (line) => (/(error|exception|traceback|critical|fatal)/i.test(line) ? 'lv-error' : /warn/i.test(line) ? 'lv-warn' : '');
  return (
    <Card title={`Logs: ${container}`} sub="around the incident" actions={<Seg value={level} options={['warn', 'error', 'all']} onChange={setLevel} />}>
      <ErrorNote>{state.error}</ErrorNote>
      <div className="logs" style={{ maxHeight: 320 }}>
        {!state.loading && state.rows.length === 0 && <div className="muted">No {level === 'all' ? '' : `${level}-level `}log lines in this window.</div>}
        {state.rows.map((r, n) => <div key={n} className={cls(r.line)}><span className="ts">{new Date(r.ts * 1000).toLocaleTimeString([], { hour12: false })}</span>{r.line}</div>)}
      </div>
    </Card>
  );
}

export default function Incident({ id }) {
  const { theme } = useApp();
  const { data: d, error, reload } = useApi(`/incidents/${encodeURIComponent(id)}`, { interval: 15000 });
  const markers = useMemo(() => {
    if (!d) return [];
    const m = [{ ts: d.incident.started_at, label: 'Alert fired', color: '#d6403f' }];
    if (d.incident.resolved_at) m.push({ ts: d.incident.resolved_at, label: 'Resolved', color: '#12a594' });
    d.deploys.forEach((x) => m.push({ ts: x.finished_at, label: `Deploy ${x.sha}`, color: undefined }));
    const loops = new Map();
    d.restarts.forEach((x) => loops.set(x.container, [...(loops.get(x.container) || []), x]));
    loops.forEach((list, container) => {
      // a crash loop is dozens of restarts: mark where it began and ended instead of striping the whole chart
      const shown = list.length > 3 ? [list[0], list[list.length - 1]] : list;
      shown.forEach((x, n) => m.push({ ts: x.ts, color: '#d8841f',
        label: list.length > 3 ? `${container}: ${n === 0 ? 'restarts begin' : `${list.length} restarts so far`}` : (x.count ? `${container} restart #${x.count}` : `${container} started`) }));
    });
    return m;
  }, [d]);
  const thresholds = useMemo(() => {
    const c = d?.chart;
    if (!c) return [];
    return [c.warn != null && { value: c.warn, color: '#d8841f', label: `warn ${fmtValue(c.warn, c.unit)}` },
      c.crit != null && { value: c.crit, color: '#d6403f', label: `critical ${fmtValue(c.crit, c.unit)}` }].filter(Boolean);
  }, [d]);

  if (!d) return error ? <div className="stack"><a href="#/alerts/active">← Alerts</a><ErrorNote>{error}</ErrorNote></div> : <div className="muted">Loading…</div>;
  const c = d.container;
  return (
    <div className="stack">
      <div><a href="#/alerts/active">← Alerts</a></div>
      <Header d={d} reload={reload} />
      <AiExplain id={id} />
      <Changed d={d} />
      {d.chart && (
        <Card title={d.chart.name} sub="dashed lines: thresholds, deploys, restarts and when it fired">
          <Chart series={d.chart.series} unit={d.chart.unit} markers={markers} thresholds={thresholds} theme={theme} />
        </Card>
      )}
      {c && (
        <div className="grid g2">
          <Card title={`${c.name}: CPU`}><Chart series={[{ name: 'CPU', points: c.cpu }]} unit="percent" kind="area" height={150} markers={markers} theme={theme} legend={false} /></Card>
          <Card title={`${c.name}: memory`}><Chart series={[{ name: 'Memory', points: c.mem }]} unit="bytes" kind="area" height={150} markers={markers} theme={theme} legend={false} /></Card>
        </div>
      )}
      {d.sentry && (
        <Card title="Sentry issues" sub="matching this alert" flush actions={<a className="btn sm" href={d.sentry.search_url} target="_blank" rel="noopener noreferrer"><Icon name="external" size={13} />Open in Sentry</a>}>
          {d.sentry.issues.length === 0 ? <Empty title="No matching issues right now" /> : <IssueTable issues={d.sentry.issues} compact />}
        </Card>
      )}
      <div className="grid g2"><Timeline d={d} /><IncidentLogs d={d} /></div>
      {d.problems.length > 0 && <div className="hint">Some context could not be loaded: {d.problems.join('; ')}</div>}
    </div>
  );
}
