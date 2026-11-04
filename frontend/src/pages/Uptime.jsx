import { useApi } from '../api';
import Announcements from '../components/Announcements';
import { Badge, Card, Empty, ErrorNote } from '../components/ui';
import { fmtAgo } from '../format';
import { PageSkeleton } from '../components/Skeleton';

export default function Uptime() {
  const { data, error } = useApi('/checks', { interval: 15000 });
  if (!data) return error ? <ErrorNote>{error}</ErrorNote> : <PageSkeleton />;
  if (data.length === 0) return <div className="stack"><Card><Empty title="No uptime checks">Add checks in nigrani.yaml, e.g. <span className="mono">{'{ id: api, name: API, type: http, target: https://api.example.com/health }'}</span>. HTTP, TCP and SSL-expiry checks are supported.</Empty></Card><Announcements /></div>;
  return (
    <div className="stack">
    <div className="grid g2">
      {data.map((c) => (
        <Card key={c.id} title={c.name} sub={c.type.toUpperCase()}
          actions={<Badge kind={c.ok === false ? 'crit' : c.ok ? 'ok' : ''} icon={c.ok === false ? 'alert' : c.ok ? 'check' : undefined}>{c.ok === false ? 'Failing' : c.ok ? 'Healthy' : 'Pending'}</Badge>}>
          <div className="mono muted" style={{ marginBottom: 8 }}>{c.target}</div>
          <div className="strip" role="img" aria-label="Recent check results, newest on the right">
            {c.history.length === 0 ? <i className="none" /> : c.history.map((h, i) => <i key={i} className={h.ok ? '' : 'bad'} title={new Date(h.ts * 1000).toLocaleTimeString()} />)}
          </div>
          <div className="row wrap" style={{ marginTop: 10 }}>
            <span>30d uptime <b>{c.uptime_30d != null ? `${c.uptime_30d.toFixed(2)}%` : '—'}</b></span>
            <span className="muted">{c.latency_ms != null ? `${c.latency_ms.toFixed(0)} ms` : c.detail}</span>
            <span className="muted right">checked {fmtAgo(c.checked_at)}</span>
          </div>
        </Card>
      ))}
    </div>
    <Announcements />
    </div>
  );
}
