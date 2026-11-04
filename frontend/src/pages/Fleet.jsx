import { useApi } from '../api';
import { Badge, Card, Empty, ErrorNote, Icon, Meter } from '../components/ui';
import { useApp } from '../ctx';
import { fmtValue } from '../format';
import { PageSkeleton } from '../components/Skeleton';

const STATUS = {
  operational: { kind: 'ok', icon: 'check' },
  degraded: { kind: 'warn', icon: 'alert' },
  major: { kind: 'crit', icon: 'alert' },
  unknown: { kind: '', icon: 'alert' },
};

function ServerCard({ f, onOpen }) {
  const st = STATUS[f.banner.status] || STATUS.unknown;
  const shown = f.tiles.filter((t) => t.value != null).slice(0, 3);
  const c = f.containers;
  return (
    <section className={`card fleet-card ${f.banner.status}`}>
      <button className="fleet-hd" onClick={onOpen} aria-label={`Open ${f.server.name}`}>
        <span className="fleet-name">{f.server.name}</span>
        {f.server.environment && f.server.environment !== f.server.name && <Badge kind="info">{f.server.environment}</Badge>}
        <span className="right"><Badge kind={st.kind} icon={st.icon}>{f.banner.title}</Badge></span>
      </button>
      <div className="bd">
        <div className="muted" style={{ minHeight: 20 }}>{f.banner.status === 'operational' ? 'No active alerts.' : f.banner.detail}</div>
        <div className="fleet-tiles">
          {shown.length === 0 && <span className="muted">No metrics yet.</span>}
          {shown.map((t) => (
            <div key={t.id} title={t.description}>
              <div className="row"><span className="muted">{t.title}</span><b className="right">{fmtValue(t.value, t.unit)}</b></div>
              <Meter value={t.value} max={t.unit === 'percent' ? 100 : Math.max(t.crit ?? t.warn ?? 1, t.value) * 1.25} warn={t.warn} crit={t.crit} status={t.status} />
            </div>
          ))}
        </div>
        <div className="row wrap" style={{ marginTop: 12 }}>
          {c && c.total > 0 && <Badge kind={c.down.length ? 'crit' : 'ok'} icon={c.down.length ? 'alert' : 'check'}>{c.up}/{c.total} containers</Badge>}
          {f.incident_counts.critical > 0 && <Badge kind="crit" icon="alert">{f.incident_counts.critical} critical</Badge>}
          {f.incident_counts.warning > 0 && <Badge kind="warn" icon="alert">{f.incident_counts.warning} warning</Badge>}
          {f.uptime_30d != null && <Badge>uptime {f.uptime_30d.toFixed(2)}%</Badge>}
          <button className="btn sm right" onClick={onOpen}>Open <Icon name="external" size={13} /></button>
        </div>
      </div>
    </section>
  );
}

/** All monitored servers at a glance. Click one to switch the dashboard to it. */
export default function Fleet() {
  const { setServer } = useApp();
  const { data, error } = useApi('/fleet', { interval: 15000 });
  if (!data) return error ? <ErrorNote>{error}</ErrorNote> : <PageSkeleton />;
  if (data.length === 0) return <Card><Empty title="No servers configured" /></Card>;
  const open = (id) => { setServer(id); window.location.hash = '/overview'; };
  return (
    <div className="grid g2">
      {data.map((f) => <ServerCard key={f.server.id} f={f} onOpen={() => open(f.server.id)} />)}
    </div>
  );
}
