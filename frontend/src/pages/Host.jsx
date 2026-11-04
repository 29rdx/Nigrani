import { useApi } from '../api';
import Chart from '../components/Chart';
import { Badge, Card, Empty, ErrorNote, Meter } from '../components/ui';
import { useApp } from '../ctx';
import { DashboardLinks } from '../components/Grafana';
import { fmtBytes, fmtDuration, fmtValue } from '../format';
import { PageSkeleton } from '../components/Skeleton';

function Stat({ label, value, sub }) {
  return <div className="card tile"><div className="t">{label}</div><div className="v" style={{ fontSize: 22 }}>{value}</div>{sub && <div className="thr">{sub}</div>}</div>;
}

export default function Host() {
  const { range, theme } = useApp();
  const { data, error } = useApi(`/host?range=${range}`, { interval: 30000 });
  if (!data) return error ? <ErrorNote>{error}</ErrorNote> : <PageSkeleton />;
  const { summary: s, series, disks } = data;
  const memUsed = s.mem_total != null && s.mem_avail != null ? s.mem_total - s.mem_avail : null;
  const swapUsed = s.swap_total ? s.swap_total - (s.swap_free || 0) : 0;
  const S = (name, points) => ({ name, points: points || [] });

  return (
    <div className="stack">
      <DashboardLinks context="host" />
      <div className="grid tiles">
        <Stat label="CPU cores" value={s.cores ?? '—'} sub={s.load1 != null ? `load ${s.load1?.toFixed(2)} · ${s.load5?.toFixed(2)} · ${s.load15?.toFixed(2)}` : null} />
        <Stat label="Memory" value={fmtBytes(memUsed)} sub={s.mem_total ? `of ${fmtBytes(s.mem_total)}` : null} />
        <Stat label="Swap" value={s.swap_total ? fmtBytes(swapUsed) : 'none'} sub={s.swap_total ? `of ${fmtBytes(s.swap_total)}` : null} />
        <Stat label="Uptime" value={fmtDuration(s.uptime)} />
      </div>
      <div className="grid g2">
        <Card title="CPU usage"><Chart series={[S('CPU', series.cpu), S('I/O wait', series.iowait)].filter((x) => x.points.length)} unit="percent" kind="area" theme={theme} /></Card>
        <Card title="Memory usage"><Chart series={[S('Memory', series.mem)].filter((x) => x.points.length)} unit="percent" kind="area" theme={theme} /></Card>
        <Card title="Network"><Chart series={[S('Receive', series.rx), S('Transmit', series.tx)].filter((x) => x.points.length)} unit="bps" theme={theme} /></Card>
        <Card title="Disk I/O"><Chart series={[S('Read', series.disk_r), S('Write', series.disk_w)].filter((x) => x.points.length)} unit="bps" theme={theme} /></Card>
      </div>
      <Card title="Disks" flush>
        {disks.length === 0 ? <Empty title="No filesystems found">node-exporter needs access to the host filesystem (mount <span className="mono">/</span> read-only).</Empty> : (
          <div className="scroll">
            <table className="t">
              <thead><tr><th>Mount</th><th>Device</th><th style={{ width: '32%' }}>Used</th><th>Free</th><th>Full in (forecast)</th></tr></thead>
              <tbody>
                {disks.map((d) => {
                  const st = d.used_pct > 90 ? 'crit' : d.used_pct > 80 ? 'warn' : 'ok';
                  return (
                    <tr key={d.device + d.mountpoint}>
                      <td className="mono">{d.mountpoint}</td>
                      <td className="muted mono">{d.device}</td>
                      <td><div className="cell-bar"><Meter value={d.used_pct} max={100} warn={80} crit={90} status={st} /><span style={{ width: 52 }}>{fmtValue(d.used_pct, 'percent')}</span></div></td>
                      <td>{fmtBytes(d.avail)} <span className="muted">/ {fmtBytes(d.size)}</span></td>
                      <td>{d.forecast_days != null ? <Badge kind={d.forecast_days < 2 ? 'crit' : d.forecast_days < 7 ? 'warn' : ''}>{d.forecast_days > 365 ? '> 1 year' : `${d.forecast_days.toFixed(1)} days`}</Badge> : <span className="muted">stable</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
