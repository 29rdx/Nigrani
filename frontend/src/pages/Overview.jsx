import { useMemo } from 'react';
import { api, useApi } from '../api';
import Chart from '../components/Chart';
import { DiscoverySuggestions } from '../components/Discovery';
import { DashboardLinks } from '../components/Grafana';
import Tile from '../components/Tile';
import { Badge, Card, Empty, ErrorNote, Icon, SevBadge } from '../components/ui';
import { useApp } from '../ctx';
import { fmtAgo, fmtValue } from '../format';

function Banner({ o }) {
  const b = o.banner;
  const icon = b.status === 'operational' ? 'check' : b.status === 'unknown' ? 'alert' : 'alert';
  return (
    <div className={`banner ${b.status}`} role="status">
      <Icon name={icon} size={26} />
      <div><h2>{b.title}</h2><div className="detail">{b.detail}</div></div>
      <div className="chips">
        {o.uptime_30d != null && <span className="chip">Uptime 30d <b>{o.uptime_30d.toFixed(2)}%</b></span>}
        {o.containers && <span className="chip">Containers <b>{o.containers.up}/{o.containers.total}</b></span>}
        <span className="chip">Prometheus <b>{o.prometheus.ok ? 'connected' : 'unreachable'}</b></span>
      </div>
    </div>
  );
}

export default function Overview() {
  const { range, theme, can } = useApp();
  const ov = useApi('/overview', { interval: 15000 });
  const host = useApi(`/host?range=${range}`, { interval: 30000 });
  const deploys = useApi('/deploys', { interval: 60000 });
  const o = ov.data;

  const series = useMemo(() => {
    const s = host.data?.series;
    if (!s) return [];
    return [{ name: 'CPU', points: s.cpu }, { name: 'Memory', points: s.mem }].filter((x) => x.points.length);
  }, [host.data]);
  const markers = useMemo(() => (deploys.data?.runs || [])
    .filter((r) => r.finished_at && r.conclusion)
    .map((r) => ({ ts: r.finished_at, label: `Deploy ${r.sha} (${r.conclusion})`, color: r.conclusion === 'success' ? undefined : '#d6403f' })), [deploys.data]);

  const silence = async (inc) => { await api('/silences', { method: 'POST', body: { server: inc.server, source_id: inc.source_id, match: inc.series || null, minutes: 60, reason: 'Silenced from overview' } }); ov.reload(); };

  if (!o) return ov.error ? <ErrorNote>{ov.error}</ErrorNote> : <div className="muted">Loading…</div>;
  const down = o.containers?.down || [];
  const bad = (o.checks || []).filter((c) => c.ok === false);

  return (
    <div>
      <Banner o={o} />
      <div style={{ marginBottom: 14 }}><DiscoverySuggestions /></div>
      <div style={{ marginBottom: 14 }}><DashboardLinks context="overview" /></div>
      <div className="grid tiles">
        {o.tiles.map((t) => <Tile key={t.id} t={t} />)}
        {o.containers && (o.containers.total === 0 ? (
          <div className="card tile">
            <div className="t"><span>Containers</span><span className="right"><Badge>No data</Badge></span></div>
            <div className="v muted">—</div>
            <div className="thr"><span>No container metrics. Is cAdvisor scraped?</span></div>
          </div>
        ) : (
          <div className={`card tile ${down.length ? 'crit' : ''}`}>
            <div className="t"><span>Containers</span><span className="right"><Badge kind={down.length ? 'crit' : 'ok'} icon={down.length ? 'alert' : 'check'}>{down.length ? `${down.length} down` : 'All up'}</Badge></span></div>
            <div className="v">{o.containers.up}<small>/ {o.containers.total} running</small></div>
            <div className="thr"><span>{down.length ? down.slice(0, 3).join(', ') + (down.length > 3 ? '…' : '') : 'No container is down'}</span></div>
          </div>
        ))}
        <div className={`card tile ${o.incident_counts.critical ? 'crit' : o.incident_counts.warning ? 'warn' : ''}`}>
          <div className="t"><span>Active alerts</span></div>
          <div className="v">{o.incident_counts.critical + o.incident_counts.warning}<small>{o.incident_counts.critical} critical · {o.incident_counts.warning} warning</small></div>
          <div className="thr"><a href="#/alerts">View alerts →</a></div>
        </div>
      </div>

      <div className="grid g2" style={{ marginTop: 14 }}>
        <Card title="CPU & memory" sub={range} actions={deploys.data?.enabled && <span className="muted">dashed lines = deploys</span>}>
          {host.error && !series.length ? <ErrorNote>{host.error}</ErrorNote> : <Chart series={series} unit="percent" kind="line" markers={markers} theme={theme} />}
        </Card>
        <Card title="Active alerts" flush actions={<a href="#/alerts">All alerts</a>}>
          {o.incidents.length === 0 ? <Empty title="Nothing firing">All rules are within their thresholds.</Empty> : (
            <div className="list">
              {o.incidents.map((i) => (
                <div key={i.id} className="row wrap">
                  <SevBadge sev={i.severity} />
                  <div style={{ minWidth: 0 }}>
                    <div><a href={`#/incident/${i.id}`}><b>{i.rule_name}</b></a> {i.series && <span className="muted">· {i.series}</span>}</div>
                    <div className="muted" style={{ fontSize: 12.5 }}>{i.last_value != null && `${fmtValue(i.last_value, i.unit)} · `}since {fmtAgo(i.started_at)}{i.silenced ? ' · silenced' : ''}{i.acked_at ? ` · acknowledged by ${i.acked_by}` : ''}</div>
                  </div>
                  {can.edit && <button className="btn sm right" onClick={() => silence(i)}>Silence 1h</button>}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 14 }}>
        <Card title="Uptime checks" flush actions={<a href="#/uptime">Details</a>}>
          {o.checks.length === 0 ? <Empty title="No checks configured">Add HTTP, TCP or SSL checks under <span className="mono">checks:</span> in nigrani.yaml.</Empty> : (
            <div className="list">
              {o.checks.map((c) => (
                <div key={c.id} className="row">
                  <span className={`dot ${c.ok === false ? 'crit' : c.ok ? 'ok' : ''}`} />
                  <b>{c.name}</b><span className="muted mono">{c.target}</span>
                  <span className="right muted">{c.latency_ms != null ? `${c.latency_ms.toFixed(0)} ms` : c.detail}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card title="Needs attention" flush>
          {down.length === 0 && bad.length === 0 ? <Empty title="All clear">No stopped containers or failing checks.</Empty> : (
            <div className="list">
              {down.map((n) => <div key={n} className="row"><Badge kind="crit" icon="alert">Down</Badge><b>{n}</b><a className="right" href="#/containers">Containers →</a></div>)}
              {bad.map((c) => <div key={c.id} className="row"><Badge kind="crit" icon="alert">Failing</Badge><b>{c.name}</b><span className="muted right">{c.detail}</span></div>)}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
