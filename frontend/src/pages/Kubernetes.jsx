import { useState } from 'react';
import { useApi } from '../api';
import { Badge, Card, Empty, ErrorNote } from '../components/ui';
import { fmtDuration } from '../format';
import { SkeletonRows } from '../components/Skeleton';

const kindOf = (p) => (p.crashloop || ['Failed', 'Unknown', 'Evicted'].includes(p.status) || p.phase === 'Failed' ? 'crit'
  : p.phase === 'Succeeded' ? '' : p.phase === 'Running' && p.ready ? 'ok' : 'warn');

function Stat({ title, value, sub, bad }) {
  return (
    <div className={`card tile ${bad ? bad : ''}`}>
      <div className="t">{title}</div>
      <div className="v">{value ?? '—'}</div>
      {sub && <div className="muted" style={{ fontSize: 12 }}>{sub}</div>}
    </div>
  );
}

export default function Kubernetes() {
  const [ns, setNs] = useState('');
  const [term, setTerm] = useState('');
  const [onlyBad, setOnlyBad] = useState(false);
  const { data, error } = useApi(`/kubernetes${ns ? `?namespace=${encodeURIComponent(ns)}` : ''}`, { interval: 30000 });
  const s = data?.summary;
  const pods = (data?.pods || []).filter((p) => (!term || `${p.namespace}/${p.name}`.includes(term)) && (!onlyBad || kindOf(p) !== 'ok' && kindOf(p) !== ''));
  return (
    <div className="stack">
      <div className="grid tiles">
        <Stat title="Nodes ready" value={s && `${s.nodes_ready}/${s.nodes}`} bad={s && s.nodes_ready < s.nodes ? 'crit' : ''} />
        <Stat title="Pods" value={s?.pods} sub={s && `${s.pods_unhealthy} not healthy`} bad={s?.pods_unhealthy ? 'warn' : ''} />
        <Stat title="Restarts in the last hour" value={s?.restarts_1h} bad={s?.restarts_1h ? 'warn' : ''} />
        <Stat title="Deployments missing replicas" value={s?.deployments_unavailable} sub={s && `of ${s.deployments}`} bad={s?.deployments_unavailable ? 'crit' : ''} />
      </div>
      <div className="row wrap">
        <select value={ns} onChange={(e) => setNs(e.target.value)} aria-label="Namespace">
          <option value="">All namespaces</option>
          {(data?.namespaces || []).map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <input type="text" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Filter pods" aria-label="Filter pods" style={{ maxWidth: 260 }} />
        <label className="row"><input type="checkbox" checked={onlyBad} onChange={(e) => setOnlyBad(e.target.checked)} /> only problems</label>
      </div>
      <ErrorNote>{error}</ErrorNote>
      {data?.nodes?.some((n) => !n.ready || n.pressure.length) && (
        <Card title="Nodes needing attention" flush>
          <div className="scroll"><table className="t"><tbody>{data.nodes.filter((n) => !n.ready || n.pressure.length).map((n) => (
            <tr key={n.name}><td><b>{n.name}</b></td><td>{n.ready ? <Badge kind="warn">{n.pressure.join(', ')}</Badge> : <Badge kind="crit">not ready</Badge>}</td><td className="muted">{n.version}</td></tr>
          ))}</tbody></table></div>
        </Card>
      )}
      {data?.deployments?.length > 0 && (
        <Card title="Deployments missing replicas" flush>
          <div className="scroll"><table className="t"><thead><tr><th>Deployment</th><th>Available</th></tr></thead><tbody>{data.deployments.map((d) => (
            <tr key={`${d.namespace}/${d.name}`}><td><b>{d.name}</b> <span className="muted">{d.namespace}</span></td><td>{d.available} / {d.desired}</td></tr>
          ))}</tbody></table></div>
        </Card>
      )}
      <Card title="Pods" sub={data?.truncated ? 'first 500 shown' : undefined} flush>
        {data && pods.length === 0 ? <Empty title="No pods match" />
          : data ? (
            <div className="scroll"><table className="t">
              <thead><tr><th>Pod</th><th>Status</th><th>Ready</th><th>Restarts</th><th>Node</th><th>Age</th></tr></thead>
              <tbody>{pods.map((p) => (
                <tr key={`${p.namespace}/${p.name}`}>
                  <td style={{ maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis' }}><b>{p.name}</b> <span className="muted">{p.namespace}</span></td>
                  <td><Badge kind={kindOf(p)}>{p.status}</Badge></td>
                  <td>{p.ready ? 'yes' : p.phase === 'Succeeded' ? '—' : 'no'}</td>
                  <td>{p.restarts}{p.restarts_1h > 0 && <span className="muted"> ({p.restarts_1h} in 1h)</span>}</td>
                  <td className="muted">{p.node || '—'}</td>
                  <td className="muted">{fmtDuration(p.age)}</td>
                </tr>
              ))}</tbody>
            </table></div>
          ) : <SkeletonRows />}
      </Card>
    </div>
  );
}
