import { useMemo, useState } from 'react';
import { api, useApi } from '../api';
import { SortTh, useSort } from '../components/SortTh';
import { useToast } from '../components/Toast';
import Chart from '../components/Chart';
import { Badge, Card, Drawer, Empty, ErrorNote, Meter } from '../components/ui';
import { useApp } from '../ctx';
import { fmtBytes, fmtDuration, fmtValue } from '../format';
import { DashboardLinks } from '../components/Grafana';
import Logs from './Logs';

function ContainerDrawer({ c, onClose, onForget }) {
  const { range, theme, me, can } = useApp();
  const m = useApi(`/containers/${encodeURIComponent(c.name)}/metrics?range=${range}`, { interval: 30000 });
  const d = m.data;
  return (
    <Drawer onClose={onClose}>
      <div className="row" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>{c.service || c.name}</h2>
        <Badge kind={c.up ? 'ok' : 'crit'} icon={c.up ? 'check' : 'alert'}>{c.up ? 'Running' : c.missing ? 'Missing' : 'Down'}</Badge>
        <button className="btn sm right" onClick={onClose}>Close</button>
      </div>
      <div className="muted mono" style={{ marginBottom: 12 }}>{c.name}</div>
      <div style={{ marginBottom: 12 }}><DashboardLinks context="container" container={c.name} /></div>
      <ErrorNote>{m.error}</ErrorNote>
      <div className="stack">
        <Card title="CPU"><Chart sync="container" series={d ? [{ name: 'CPU', points: d.cpu }] : []} unit="percent" kind="area" height={150} theme={theme} /></Card>
        <Card title="Memory"><Chart sync="container" series={d ? [{ name: 'Working set', points: d.mem }] : []} unit="bytes" kind="area" height={150} theme={theme} /></Card>
        <Card title="Network"><Chart sync="container" series={d ? [{ name: 'Receive', points: d.rx }, { name: 'Transmit', points: d.tx }] : []} unit="bps" height={150} theme={theme} /></Card>
        {me?.features?.logs && <Card title="Recent logs"><Logs embedded container={c.name} /></Card>}
        {c.auto && can.edit && <button className="btn danger" onClick={() => onForget(c)}>Stop tracking this container</button>}
      </div>
    </Drawer>
  );
}

export default function Containers() {
  const toast = useToast();
  const { data, error, reload } = useApi('/containers', { interval: 15000 });
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState('all');
  const [sel, setSel] = useState(null);

  const sort = useSort({ status: (c) => (c.up ? 1 : 0), name: (c) => c.service || c.name, cpu: (c) => c.cpu, mem: (c) => c.mem_pct ?? c.mem,
    restarts: (c) => c.restarts_1h || 0, uptime: (c) => (c.up ? c.uptime : null), net: (c) => (c.rx || 0) + (c.tx || 0) });
  const rows = useMemo(() => sort.apply((data || []).filter((c) => {
    if (q && !`${c.name} ${c.service || ''}`.toLowerCase().includes(q.toLowerCase())) return false;
    if (filter === 'down') return !c.up;
    if (filter === 'restarting') return (c.restarts_1h || 0) > 0;
    return true;
  })), [data, q, filter, sort.apply]);

  const forget = async (c) => { if (await toast.run(() => api(`/containers/${encodeURIComponent(c.name)}`, { method: 'DELETE' }), `Forgot “${c.name}”`)) { setSel(null); reload(); } };
  const up = (data || []).filter((c) => c.up).length;

  return (
    <div className="stack">
      <div className="row wrap">
        <input type="text" placeholder="Filter containers…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 260 }} aria-label="Filter containers" />
        <div className="seg">
          {['all', 'down', 'restarting'].map((f) => <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>{f}</button>)}
        </div>
        {data && <span className="muted right">{up} of {data.length} running</span>}
      </div>
      <ErrorNote>{error}</ErrorNote>
      <Card flush>
        {data && rows.length === 0 ? <Empty title="No containers match">Make sure cAdvisor is scraped by Prometheus.</Empty> : (
          <div className="scroll">
            <table className="t">
              <thead><tr><SortTh label="Status" k="status" sort={sort} /><SortTh label="Container" k="name" sort={sort} /><SortTh label="CPU" k="cpu" sort={sort} /><SortTh label="Memory" k="mem" sort={sort} /><SortTh label="Restarts (1h)" k="restarts" sort={sort} /><SortTh label="Uptime" k="uptime" sort={sort} /><SortTh label="Net in / out" k="net" sort={sort} /></tr></thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.name} className="click" onClick={() => setSel(c)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setSel(c)}>
                    <td><Badge kind={c.up ? 'ok' : 'crit'} icon={c.up ? 'check' : 'alert'}>{c.up ? 'Up' : c.missing ? 'Missing' : 'Down'}</Badge></td>
                    <td><b>{c.service || c.name}</b>{c.service && c.service !== c.name && <div className="muted mono">{c.name}</div>}{c.auto && <div className="muted" style={{ fontSize: 12 }}>auto-tracked</div>}</td>
                    <td><div className="cell-bar"><Meter value={Math.min(c.cpu ?? 0, 100)} max={100} status={(c.cpu || 0) > 90 ? 'crit' : (c.cpu || 0) > 70 ? 'warn' : 'ok'} /><span style={{ width: 52 }}>{c.cpu != null ? `${c.cpu.toFixed(1)}%` : '—'}</span></div></td>
                    <td>{c.mem_pct != null
                      ? <div className="cell-bar"><Meter value={c.mem_pct} max={100} status={c.mem_pct > 90 ? 'crit' : c.mem_pct > 75 ? 'warn' : 'ok'} /><span style={{ width: 92 }}>{fmtBytes(c.mem)}</span></div>
                      : fmtBytes(c.mem)}</td>
                    <td>{c.restarts_1h ? <Badge kind={c.restarts_1h > 2 ? 'crit' : 'warn'} icon="alert">{c.restarts_1h}</Badge> : <span className="muted">0</span>}</td>
                    <td>{c.up ? fmtDuration(c.uptime) : '—'}</td>
                    <td className="muted">{fmtValue(c.rx, 'bps')} / {fmtValue(c.tx, 'bps')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {sel && <ContainerDrawer c={sel} onClose={() => setSel(null)} onForget={forget} />}
    </div>
  );
}
