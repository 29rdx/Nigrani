import { useState } from 'react';
import { api, useApi } from '../api';
import { useApp } from '../ctx';
import { useToast } from './Toast';
import { Badge, Card, ErrorNote, Icon } from './ui';

const LABEL = { enabled: ['ok', 'On'], found: ['info', 'Found'], missing: ['', 'Not detected'] };

function counts(p) {
  return [p.pages > 0 && `${p.pages} page${p.pages > 1 ? 's' : ''}`, p.tiles > 0 && `${p.tiles} tile${p.tiles > 1 ? 's' : ''}`,
    p.rules > 0 && `${p.rules} alert rule${p.rules > 1 ? 's' : ''}`].filter(Boolean).join(', ');
}

function useDiscovery(shared) {
  const own = useApi('/discovery', { interval: 60000, enabled: !shared });       // the Overview shares its own fetch so nothing jumps when it arrives
  const { data, error, reload } = shared || own;
  const toast = useToast();
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const change = async (name, on) => {
    setBusy(name); setErr(null);
    try {
      await api(on ? `/discovery/${name}/enable` : `/discovery/${name}`, { method: on ? 'POST' : 'DELETE' });
      await reload();
      window.dispatchEvent(new Event('nigrani:presets'));          // the menu and the pages list pick the change up
      const title = data?.presets?.find((p) => p.name === name)?.title || name;
      toast.ok(on ? `${title} is on: its page and alert rules are live` : `${title} turned off`);
    } catch (e) { setErr(e.message); toast.err(e.message); }
    setBusy(null);
  };
  return { data, error, err, busy, change };
}

/** Overview: "we found Redis in your Prometheus, turn it on?". Shows nothing when there is nothing to suggest. */
export function DiscoverySuggestions({ shared }) {
  const { can } = useApp();
  const { data, err, busy, change } = useDiscovery(shared);
  const [hidden, setHidden] = useState(false);
  const found = (data?.presets || []).filter((p) => p.status === 'found');
  if (hidden || found.length === 0) return null;
  return (
    <Card title="Found in your Prometheus" sub="dashboards and alert rules that fit what you are already collecting"
      actions={<button className="btn sm" onClick={() => setHidden(true)} aria-label="Hide suggestions"><Icon name="x" size={13} /></button>}>
      <div className="stack" style={{ gap: 10 }}>
        {found.map((p) => (
          <div key={p.name} className="row wrap">
            <Icon name="sparkle" size={15} />
            <div style={{ flex: 1, minWidth: 200 }}>
              <b>{p.title}</b> <span className="muted">· {counts(p)}</span>
              <div className="muted" style={{ fontSize: 13 }}>{p.about}</div>
            </div>
            {can.edit && <button className="btn primary sm" onClick={() => change(p.name, true)} disabled={busy === p.name}>{busy === p.name ? 'Turning on…' : 'Turn on'}</button>}
          </div>
        ))}
        {!can.edit && <div className="hint">An editor can turn these on.</div>}
      </div>
    </Card>
  );
}

/** Integrations: every preset Nigrani can recognise, what was detected, and a switch for the ones you turned on here. */
export function DiscoveryList() {
  const { can } = useApp();
  const { data, error, err, busy, change } = useDiscovery();
  if (!data) return error ? <ErrorNote>{error}</ErrorNote> : null;
  return (
    <Card title="Auto-discovery" sub="Nigrani reads the metric names in Prometheus and suggests what to monitor" flush>
      {data.error && <div style={{ padding: '10px 16px' }}><ErrorNote>{data.error}</ErrorNote></div>}
      <div className="list">
        {data.presets.map((p) => {
          const [kind, text] = LABEL[p.status];
          return (
            <div key={p.name} className="row wrap">
              <Badge kind={kind}>{text}</Badge>
              <div style={{ flex: 1, minWidth: 200 }}>
                <b>{p.title}</b> <span className="muted">· {counts(p)}</span>
                <div className="muted" style={{ fontSize: 13 }}>{p.about}</div>
                {p.status === 'missing' && <div className="muted" style={{ fontSize: 12 }}>Looks for the metric <span className="mono">{p.detect.join(', ')}</span></div>}
                {p.origin === 'config' && <div className="muted" style={{ fontSize: 12 }}>Enabled in nigrani.yaml</div>}
              </div>
              {can.edit && p.status === 'found' && <button className="btn primary sm" onClick={() => change(p.name, true)} disabled={busy === p.name}>Turn on</button>}
              {can.edit && p.origin === 'ui' && <button className="btn sm" onClick={() => change(p.name, false)} disabled={busy === p.name}>Turn off</button>}
              {can.edit && p.status === 'missing' && <button className="btn sm" onClick={() => change(p.name, true)} disabled={busy === p.name} title="Turn it on anyway">Turn on anyway</button>}
            </div>
          );
        })}
      </div>
      {err && <div style={{ padding: '10px 16px' }}><ErrorNote>{err}</ErrorNote></div>}
    </Card>
  );
}
