import { useApi } from '../api';
import { Badge, Card, Empty, ErrorNote } from '../components/ui';

const STATUS = { ok: ['ok', 'Within budget'], warning: ['warn', 'Burning budget'], critical: ['crit', 'Budget in danger'], nodata: ['', 'No data yet'], error: ['warn', 'Cannot evaluate'] };
const win = (s) => (s % 86400 === 0 ? `${s / 86400}d` : s % 3600 === 0 ? `${s / 3600}h` : `${s / 60}m`);
const x = (v) => (v == null ? '—' : `${v < 10 ? v.toFixed(1) : Math.round(v)}×`);
const mins = (m) => (m == null ? '—' : m >= 120 ? `${(m / 60).toFixed(1)} h` : `${m.toFixed(m < 10 ? 1 : 0)} min`);

/** The share of the error budget that is left, as a bar that turns amber and red as it runs down. */
export function BudgetBar({ remaining }) {
  const pct = remaining == null ? 0 : Math.max(0, Math.min(1, remaining)) * 100;
  const color = remaining == null ? 'var(--border)' : remaining > 0.5 ? 'var(--ok)' : remaining > 0.2 ? 'var(--warn)' : 'var(--crit)';
  return (
    <div role="img" aria-label={remaining == null ? 'No data' : `${Math.round(pct)}% of the error budget left`}
      style={{ height: 10, borderRadius: 5, background: 'var(--surface-2)', overflow: 'hidden', border: '1px solid var(--border)' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: color, transition: 'width .3s' }} />
    </div>
  );
}

function Slo({ s }) {
  const [kind, label] = STATUS[s.status] || STATUS.nodata;
  const left = s.budget_remaining;
  return (
    <Card title={s.name} sub={`${s.target}% over ${s.window_days} days${s.source && s.source !== 'prometheus' ? ` · ${s.source}` : ''}`}
      actions={<Badge kind={kind}>{label}</Badge>}>
      {s.error && <ErrorNote>{s.error}</ErrorNote>}
      {s.description && <div className="muted" style={{ marginBottom: 8 }}>{s.description}</div>}
      <div className="row wrap" style={{ alignItems: 'baseline', gap: 24 }}>
        <div><div className="muted" style={{ fontSize: 12 }}>Right now</div>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{s.sli == null ? '—' : `${s.sli.toFixed(s.sli > 99.9 ? 3 : 2)}%`}</div></div>
        <div><div className="muted" style={{ fontSize: 12 }}>Objective</div><div style={{ fontSize: 28, fontWeight: 700 }}>{s.target}%</div></div>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
            Error budget left: <b style={{ color: 'var(--text)' }}>{left == null ? '—' : `${Math.round(left * 100)}%`}</b>
            {left != null && s.budget_minutes != null && <> · {mins(Math.max(0, s.budget_minutes - (s.budget_used_minutes || 0)))} of {mins(s.budget_minutes)}</>}
          </div>
          <BudgetBar remaining={left} />
        </div>
      </div>
      {s.tiers.length > 0 && (
        <div className="scroll" style={{ marginTop: 12 }}><table className="t">
          <thead><tr><th>Alert</th><th>Windows</th><th>Burn rate (long / short)</th><th>Alerts above</th><th /></tr></thead>
          <tbody>{s.tiers.map((t) => (
            <tr key={t.name}>
              <td><b>{{ fast: 'Fast burn', slow: 'Slow burn', daily: 'Steady burn', trend: 'Gradual burn' }[t.name]}</b> <span className="muted">{t.severity}</span></td>
              <td className="mono">{win(t.long)} &amp; {win(t.short)}</td>
              <td>{x(t.burn_long)} / {x(t.burn_short)}</td>
              <td>{t.factor}×</td>
              <td>{t.firing ? <Badge kind={t.severity === 'critical' ? 'crit' : 'warn'}>firing</Badge> : <Badge kind="ok">ok</Badge>}</td>
            </tr>))}</tbody>
        </table></div>
      )}
    </Card>
  );
}

export default function SLOs() {
  const { data, error } = useApi('/slos', { interval: 30000 });
  if (!data) return error ? <ErrorNote>{error}</ErrorNote> : <div className="muted">Loading…</div>;
  if (data.slos.length === 0) {
    return <Card><Empty title="No SLOs for this server">Add one under <span className="mono">slos:</span> in nigrani.yaml: a target such as 99.9% over 30 days and how to count good and total events (or an uptime check). Nigrani then alerts when the error budget burns too fast. See the README.</Empty></Card>;
  }
  return <div className="stack">{data.slos.map((s) => <Slo key={s.id} s={s} />)}</div>;
}
