import { useApi } from '../api';
import { Badge, Card, Empty, ErrorNote, Icon } from '../components/ui';
import { dayClass, fmtDateTime, fmtDuration } from '../format';

const TEXT = { operational: 'All systems operational', degraded: 'Partial degradation', major: 'Major outage', maintenance: 'Scheduled maintenance in progress' };
const KIND = { incident: { kind: 'crit', label: 'Incident' }, maintenance: { kind: 'info', label: 'Maintenance' }, info: { kind: '', label: 'Notice' } };
const STATE = { scheduled: 'Scheduled', resolved: 'Resolved', active: 'In progress', completed: 'Completed' };

export function Bars({ days }) {
  return (
    <div className="daybars" role="img" aria-label={`Daily uptime for the last ${days.length} days, oldest on the left`}>
      {days.map((d) => <i key={d.day} className={dayClass(d.pct)} title={`${d.day}: ${d.pct == null ? 'no data' : `${d.pct.toFixed(2)}% up`}`} />)}
    </div>
  );
}

export function Announcement({ a }) {
  const k = KIND[a.kind] || KIND.info;
  return (
    <div className="row" style={{ alignItems: 'flex-start' }}>
      <Badge kind={a.state === 'resolved' || a.state === 'completed' ? 'ok' : k.kind}>{k.label}</Badge>
      <div style={{ flex: 1, minWidth: 0 }}>
        <b>{a.title}</b>
        {a.body && <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{a.body}</div>}
        <div className="muted" style={{ fontSize: 12 }}>
          {STATE[a.state]} · {fmtDateTime(a.starts_at)}{a.ends_at ? ` → ${fmtDateTime(a.ends_at)}` : ''}{a.resolved_at ? ` · resolved ${fmtDateTime(a.resolved_at)}` : ''}
        </div>
      </div>
    </div>
  );
}

/** Public status page (enabled with status_page.enabled). No login, minimal data. */
export default function Status() {
  const { data, error } = useApi('/public/status', { interval: 30000 });
  if (error) return <div className="pub"><ErrorNote>{error}</ErrorNote></div>;
  if (!data) return <div className="pub muted">Loading…</div>;
  const notes = data.announcements || [];
  return (
    <div className="pub stack">
      <h1 style={{ margin: 0 }}>{data.title}</h1>
      <div className={`banner ${data.status}`}><Icon name={data.status === 'operational' ? 'check' : 'alert'} size={26} /><h2>{TEXT[data.status]}</h2></div>
      {notes.length > 0 && <Card title="Updates" flush><div className="list">{notes.map((a) => <Announcement key={a.id} a={a} />)}</div></Card>}
      <Card title="Services" flush>
        {data.checks.length === 0 ? <Empty title="No public checks" /> : (
          <div className="list">{data.checks.map((c) => (
            <div key={c.name} className="svc">
              <div className="row"><span className={`dot ${c.ok === false ? 'crit' : c.ok ? 'ok' : ''}`} /><b>{c.name}</b>
                <span className="muted right">{c.uptime_period != null ? `${c.uptime_period.toFixed(2)}% (${data.period_days}d)` : ''}</span>
                <Badge kind={c.ok === false ? 'crit' : 'ok'}>{c.ok === false ? 'Down' : 'Operational'}</Badge></div>
              {c.days && <Bars days={c.days} />}
              {c.days && <div className="daylegend muted"><span>{data.period_days} days ago</span><span>Today</span></div>}
            </div>))}</div>
        )}
      </Card>
      <Card title="Past 7 days" flush>
        {data.incidents.length === 0 ? <Empty title="No incidents" /> : (
          <div className="list">{data.incidents.map((i, n) => (
            <div key={n} className="row"><Badge kind={i.severity === 'critical' ? 'crit' : 'warn'}>{i.severity}</Badge><b>{i.rule}</b>
              <span className="muted right">{fmtDateTime(i.started_at)} · {i.resolved_at ? `resolved after ${fmtDuration(i.resolved_at - i.started_at)}` : 'ongoing'}</span></div>))}</div>
        )}
      </Card>
    </div>
  );
}
