import { useApi } from '../api';
import { Badge, Card, Empty, ErrorNote, Icon } from '../components/ui';
import { fmtAgo } from '../format';
import { SkeletonRows } from '../components/Skeleton';

const KIND = { Alert: 'crit', 'No Data': 'warn', Warn: 'warn' };

function Stat({ title, n, bad }) {
  return (
    <div className={`card tile ${n > 0 && bad ? bad : ''}`}>
      <div className="t">{title}</div>
      <div className="v">{n ?? '—'}</div>
    </div>
  );
}

export default function Datadog() {
  const { data, error } = useApi('/datadog/monitors', { interval: 60000 });
  const c = data?.counts || {};
  return (
    <div className="stack">
      <div className="grid tiles">
        <Stat title="Alerting" n={data && (c.Alert || 0)} bad="crit" />
        <Stat title="Warning" n={data && (c.Warn || 0)} bad="warn" />
        <Stat title="No data" n={data && (c['No Data'] || 0)} bad="warn" />
        <Stat title="OK" n={data && (c.OK || 0)} />
      </div>
      <ErrorNote>{error}</ErrorNote>
      <Card title="Monitors that are not OK" sub={data ? `${data.total} monitors in total` : undefined} flush
        actions={data?.app_url && <a className="btn sm" href={`${data.app_url}/monitors/manage`} target="_blank" rel="noopener noreferrer"><Icon name="external" size={13} />Open in Datadog</a>}>
        {data && data.monitors.length === 0 ? <Empty title="Every monitor is OK" />
          : data ? (
            <div className="scroll"><table className="t">
              <thead><tr><th>Monitor</th><th>State</th><th>Since</th><th>Tags</th></tr></thead>
              <tbody>{data.monitors.map((m) => (
                <tr key={m.id}>
                  <td style={{ maxWidth: 520 }}><a href={m.url} target="_blank" rel="noopener noreferrer"><b>{m.name}</b></a><div className="muted mono" style={{ fontSize: 12 }}>{m.type}</div></td>
                  <td><Badge kind={KIND[m.state] || ''}>{m.state}</Badge></td>
                  <td className="muted">{m.since ? fmtAgo(m.since) : '—'}</td>
                  <td className="muted mono" style={{ fontSize: 12 }}>{m.tags.join(' ')}</td>
                </tr>
              ))}</tbody>
            </table></div>
          ) : <SkeletonRows />}
      </Card>
    </div>
  );
}
