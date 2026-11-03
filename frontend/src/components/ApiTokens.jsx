import { useState } from 'react';
import { api, useApi } from '../api';
import { fmtAgo, fmtDateTime } from '../format';
import { Badge, Card, Empty, ErrorNote, Icon, Modal } from './ui';

function NewToken({ onClose, onCreated }) {
  const [f, setF] = useState({ name: '', role: 'viewer', days: '' });
  const [made, setMade] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const create = async () => {
    setBusy(true); setErr(null);
    try { setMade(await api('/tokens', { method: 'POST', body: { name: f.name, role: f.role, days: f.days ? Number(f.days) : null } })); onCreated(); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const copy = async () => { try { await navigator.clipboard.writeText(made.token); setCopied(true); } catch { /* the field below can be selected by hand */ } };
  if (made) {
    return (
      <Modal title="Token created" onClose={onClose} actions={<button className="btn primary" onClick={onClose}>Done</button>}>
        <div className="notice">Copy it now. It is shown only once and Nigrani keeps just a hash.</div>
        <div className="row" style={{ marginTop: 10 }}>
          <input type="text" readOnly value={made.token} aria-label="API token" style={{ flex: 1, fontFamily: 'monospace' }} onFocus={(e) => e.target.select()} />
          <button className="btn" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        </div>
        <div className="hint" style={{ marginTop: 10 }}>
          Use it as <span className="mono">Authorization: Bearer &lt;token&gt;</span> on the API, or to connect an AI assistant:
          <pre className="mono" style={{ whiteSpace: 'pre-wrap', margin: '6px 0 0' }}>{`claude mcp add --transport http nigrani ${window.location.origin}/mcp --header "Authorization: Bearer <token>"`}</pre>
        </div>
      </Modal>
    );
  }
  return (
    <Modal title="New API token" onClose={onClose} actions={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" onClick={create} disabled={busy || !f.name.trim()}>Create</button></>}>
      <label className="f" htmlFor="t-name">Name</label>
      <input id="t-name" type="text" value={f.name} onChange={set('name')} placeholder="e.g. Claude Code (alex)" autoFocus maxLength={60} />
      <label className="f" htmlFor="t-role">Access</label>
      <select id="t-role" value={f.role} onChange={set('role')}>
        <option value="viewer">Viewer: read only (enough for an AI assistant)</option>
        <option value="editor">Editor: can also change alerts, channels and silences</option>
      </select>
      <label className="f" htmlFor="t-days">Expires after (days)</label>
      <input id="t-days" type="number" min="1" max="3650" value={f.days} onChange={set('days')} placeholder="never" />
      <ErrorNote>{err}</ErrorNote>
    </Modal>
  );
}

/** Admin: long-lived credentials for scripts and AI assistants (they never get the admin role). */
export default function ApiTokens() {
  const { data, error, reload } = useApi('/tokens', { interval: 60000 });
  const [adding, setAdding] = useState(false);
  const [problem, setProblem] = useState(null);
  const revoke = async (t) => {
    if (!window.confirm(`Revoke "${t.name}"? Anything using it stops working.`)) return;
    setProblem(null);
    try { await api(`/tokens/${t.id}`, { method: 'DELETE' }); reload(); } catch (e) { setProblem(e.message); }
  };
  return (
    <Card title="API tokens" sub="for scripts and AI assistants (MCP)" flush
      actions={<button className="btn sm primary" onClick={() => setAdding(true)}><Icon name="plus" size={13} />New token</button>}>
      <ErrorNote>{error || problem}</ErrorNote>
      {data && data.length === 0 ? <Empty title="No tokens yet">Create one to let a script, or an assistant such as Claude Code, read from Nigrani.</Empty> : (
        <div className="scroll"><table className="t">
          <thead><tr><th>Name</th><th>Access</th><th>Token</th><th>Last used</th><th>Expires</th><th /></tr></thead>
          <tbody>{(data || []).map((t) => (
            <tr key={t.id}>
              <td><b>{t.name}</b><div className="muted" style={{ fontSize: 12 }}>by {t.created_by}</div></td>
              <td><Badge kind={t.role === 'editor' ? 'warn' : 'info'}>{t.role}</Badge></td>
              <td className="mono muted">{t.prefix}…</td>
              <td className="muted">{t.last_used ? fmtAgo(t.last_used) : 'never'}</td>
              <td className="muted">{t.expires_at ? fmtDateTime(t.expires_at) : 'never'}</td>
              <td><button className="btn sm danger" onClick={() => revoke(t)}>Revoke</button></td>
            </tr>))}</tbody>
        </table></div>
      )}
      {adding && <NewToken onClose={() => setAdding(false)} onCreated={reload} />}
    </Card>
  );
}
