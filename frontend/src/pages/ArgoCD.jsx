import { useState } from 'react';
import { useApi } from '../api';
import { Badge, Card, Empty, ErrorNote, Icon } from '../components/ui';
import { fmtAgo } from '../format';

const HEALTH = { Healthy: 'ok', Progressing: 'info', Suspended: '', Degraded: 'crit', Missing: 'crit', Unknown: 'warn' };
const SYNC = { Synced: 'ok', OutOfSync: 'warn', Unknown: 'warn' };
const failing = (a) => a.op_phase === 'Failed' || a.op_phase === 'Error' || (a.op_phase === 'Running' && a.retries > 0);
const troubled = (a) => a.sync !== 'Synced' || !['Healthy', 'Suspended'].includes(a.health) || failing(a) || a.errors.length > 0;

function Stat({ title, value, sub, bad }) {
  return (
    <div className={`card tile ${bad || ''}`}>
      <div className="t">{title}</div>
      <div className="v">{value ?? '—'}</div>
      {sub && <div className="muted" style={{ fontSize: 12 }}>{sub}</div>}
    </div>
  );
}

function Detail({ a }) {
  const lines = [
    ...a.errors.map((e) => `${e.type}: ${e.message}`),
    ...(failing(a) && a.op_message ? [`Last sync${a.retries ? ` (retry ${a.retries})` : ''}: ${a.op_message}`] : []),
    ...(a.health !== 'Healthy' && a.health_message ? [`Health: ${a.health_message}`] : []),
  ];
  if (lines.length === 0) return null;
  return <div className="muted" style={{ fontSize: 12, whiteSpace: 'pre-wrap', maxWidth: 560 }}>{lines.join('\n')}</div>;
}

export default function ArgoCD() {
  const [project, setProject] = useState('');
  const [term, setTerm] = useState('');
  const [onlyBad, setOnlyBad] = useState(false);
  const { data, error } = useApi(`/argocd${project ? `?project=${encodeURIComponent(project)}` : ''}`, { interval: 30000 });
  const s = data?.summary;
  const apps = (data?.apps || []).filter((a) => (!term || a.name.includes(term)) && (!onlyBad || troubled(a)));
  return (
    <div className="stack">
      <div className="grid tiles">
        <Stat title="Applications" value={s?.total} sub={s && `${s.healthy} healthy`} />
        <Stat title="Out of sync" value={s?.out_of_sync} bad={s?.out_of_sync ? 'warn' : ''} />
        <Stat title="Degraded or missing" value={s?.degraded} bad={s?.degraded ? 'crit' : ''} />
        <Stat title="Sync failing or errors" value={s?.failed} bad={s?.failed ? 'crit' : ''} />
      </div>
      <div className="row wrap">
        <select value={project} onChange={(e) => setProject(e.target.value)} aria-label="Project">
          <option value="">All projects</option>
          {(data?.projects || []).map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <input type="text" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Filter applications" aria-label="Filter applications" style={{ maxWidth: 260 }} />
        <label className="row"><input type="checkbox" checked={onlyBad} onChange={(e) => setOnlyBad(e.target.checked)} /> only problems</label>
        {data?.url && <a className="btn sm right" href={data.url} target="_blank" rel="noopener noreferrer"><Icon name="external" size={13} />Open Argo CD</a>}
      </div>
      <ErrorNote>{error}</ErrorNote>
      <Card title="Applications" sub={data?.truncated ? 'first 500 shown' : undefined} flush>
        {data && apps.length === 0 ? <Empty title="No applications match" />
          : data ? (
            <div className="scroll"><table className="t">
              <thead><tr><th>Application</th><th>Health</th><th>Sync</th><th>Revision</th><th>Last sync</th></tr></thead>
              <tbody>{apps.map((a) => (
                <tr key={a.name}>
                  <td style={{ maxWidth: 460 }}><b>{a.name}</b> <span className="muted">{a.project} · {a.namespace || a.cluster}</span>
                    <div className="muted mono" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis' }} title={a.repo}>{a.path || '/'}@{a.target}{a.auto_sync ? ' · auto-sync' : ''}</div>
                    <Detail a={a} />
                  </td>
                  <td><Badge kind={HEALTH[a.health] ?? 'warn'}>{a.health}</Badge></td>
                  <td><Badge kind={SYNC[a.sync] ?? 'warn'}>{a.sync}</Badge>{failing(a) && <> <Badge kind="crit">sync failing</Badge></>}</td>
                  <td className="mono muted">{a.revision || '—'}</td>
                  <td className="muted">{a.last_sync_at ? fmtAgo(a.last_sync_at) : '—'}</td>
                </tr>
              ))}</tbody>
            </table></div>
          ) : <div className="empty muted">Loading…</div>}
      </Card>
    </div>
  );
}
