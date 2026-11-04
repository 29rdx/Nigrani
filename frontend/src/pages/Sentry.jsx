import { useState } from 'react';
import { useApi } from '../api';
import { Badge, Card, Empty, ErrorNote, Icon, Seg } from '../components/ui';
import { fmtAgo } from '../format';
import { SkeletonRows } from '../components/Skeleton';

const LEVEL = { fatal: 'crit', error: 'crit', warning: 'warn', info: 'info', debug: '' };
const SORTS = ['date', 'freq', 'new', 'user', 'priority'];

export function IssueTable({ issues, compact = false }) {
  return (
    <div className="scroll"><table className="t">
      <thead><tr><th>Issue</th>{!compact && <th>Project</th>}<th>Events</th><th>Users</th><th>First seen</th><th>Last seen</th></tr></thead>
      <tbody>{issues.map((i) => (
        <tr key={i.id}>
          <td style={{ maxWidth: 520 }}>
            <Badge kind={LEVEL[i.level] ?? ''}>{i.level || '?'}</Badge>{' '}
            <a href={i.url} target="_blank" rel="noopener noreferrer"><b>{i.title}</b></a>
            <div className="muted mono" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{i.short_id}{i.culprit ? ` · ${i.culprit}` : ''}</div>
          </td>
          {!compact && <td>{i.project_name}</td>}
          <td>{i.count.toLocaleString()}</td>
          <td>{i.users.toLocaleString()}</td>
          <td className="muted">{i.first_seen ? fmtAgo(i.first_seen) : '—'}</td>
          <td className="muted">{i.last_seen ? fmtAgo(i.last_seen) : '—'}</td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}

function Stat({ title, s, bad }) {
  const n = s ? `${s.count}${s.capped ? '+' : ''}` : '—';
  return (
    <div className={`card tile ${s && s.count > 0 && bad ? bad : ''}`}>
      <div className="t">{title}</div>
      <div className="v">{n}</div>
    </div>
  );
}

export default function Sentry() {
  const [query, setQuery] = useState('is:unresolved');
  const [term, setTerm] = useState('is:unresolved');
  const [sort, setSort] = useState('date');
  const summary = useApi('/sentry/summary', { interval: 60000 });
  const list = useApi(`/sentry/issues?query=${encodeURIComponent(term)}&sort=${sort}&limit=50`, { interval: 60000 });
  const submit = (e) => { e.preventDefault(); setTerm(query.trim() || 'is:unresolved'); };
  const s = summary.data;
  return (
    <div className="stack">
      <div className="grid tiles">
        <Stat title="Unresolved" s={s?.unresolved} />
        <Stat title="New in the last hour" s={s?.new_1h} bad="warn" />
        <Stat title="New in the last 24 hours" s={s?.new_24h} />
        <Stat title="Fatal" s={s?.fatal} bad="crit" />
      </div>
      <form className="row wrap" onSubmit={submit}>
        <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} style={{ maxWidth: 420 }} aria-label="Sentry search" placeholder="is:unresolved level:error" />
        <button className="btn">Search</button>
        <span className="muted">sort</span><Seg value={sort} options={SORTS} onChange={setSort} />
        {list.data?.search_url && <a className="btn sm right" href={list.data.search_url} target="_blank" rel="noopener noreferrer"><Icon name="external" size={13} />Open in Sentry</a>}
      </form>
      <ErrorNote>{list.error || summary.error}</ErrorNote>
      <Card flush>
        {list.data && list.data.issues.length === 0 ? <Empty title="No issues match">Try a broader search, for example <span className="mono">is:unresolved</span>.</Empty>
          : list.data ? <IssueTable issues={list.data.issues} /> : <SkeletonRows />}
      </Card>
    </div>
  );
}
