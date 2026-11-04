import { useApi } from '../api';
import Chart from '../components/Chart';
import { Card, Empty, ErrorNote } from '../components/ui';
import { useApp } from '../ctx';
import { fmtValue } from '../format';
import { PageSkeleton } from '../components/Skeleton';

/** Renders any page defined in nigrani.yaml / presets (Traffic, Redis, Postgres, MQTT, ...). */
export default function PanelPage({ id }) {
  const { range, theme } = useApp();
  const { data, error } = useApi(`/pages/${encodeURIComponent(id)}?range=${range}`, { interval: 30000 });
  if (!data) return error ? <ErrorNote>{error}</ErrorNote> : <PageSkeleton />;
  if (!data.available) {
    return (
      <Card>
        <Empty title={`${data.title} metrics not detected`}>
          {data.hint || 'Prometheus has no data for this page yet.'}
          {data.requires && <div className="mono" style={{ marginTop: 8 }}>expects metric: {data.requires}</div>}
        </Empty>
      </Card>
    );
  }
  return (
    <div className="grid g2">
      {data.panels.map((p) => (
        <Card key={p.title} title={p.title} className={p.wide ? 'wide' : ''}>
          {p.error ? <ErrorNote>{p.error}</ErrorNote>
            : p.kind === 'stat' ? <div className="tile"><div className="v">{fmtValue(p.value, p.unit)}</div></div>
              : <Chart sync={`page-${id}`} label={p.title} series={p.series} unit={p.unit} kind={p.kind} theme={theme} />}
          {p.description && <div className="hint">{p.description}</div>}
        </Card>
      ))}
    </div>
  );
}
