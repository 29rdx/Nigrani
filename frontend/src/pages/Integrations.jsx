import { useEffect, useState } from 'react';
import { api, useApi } from '../api';
import { DiscoveryList } from '../components/Discovery';
import { Badge, Card, Empty, ErrorNote, Modal, Seg, Toggle } from '../components/ui';
import { useApp } from '../ctx';
import { fmtAgo } from '../format';

const TYPES = { slack: 'Slack', teams: 'Microsoft Teams', discord: 'Discord', telegram: 'Telegram', whatsapp: 'WhatsApp (Twilio)', email: 'Email (SMTP)', webhook: 'Generic webhook' };
const SEVS = [['info', 'Everything'], ['warning', 'Warnings & critical'], ['critical', 'Critical only']];

/** Optional per-channel title/body templates with {placeholders} and a live preview on a sample alert. */
function MessageEditor({ f, setF }) {
  const ph = useApi('/message-placeholders');
  const [kind, setKind] = useState('firing');
  const [prev, setPrev] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!f.title_template && !f.body_template) { setPrev(null); setErr(null); return undefined; }
    const t = setTimeout(async () => {
      try {
        setPrev(await api('/channels/preview', { method: 'POST', body: { title_template: f.title_template || null, body_template: f.body_template || null, kind } }));
        setErr(null);
      } catch (e) { setPrev(null); setErr(e.message); }
    }, 400);
    return () => clearTimeout(t);
  }, [f.title_template, f.body_template, kind]);

  return (
    <details open={!!(f.title_template || f.body_template)} style={{ marginTop: 14 }}>
      <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Custom message (optional)</summary>
      <label className="f" htmlFor="c-title-t">Title</label>
      <input id="c-title-t" type="text" value={f.title_template || ''} placeholder="{emoji} {rule} on {server}: {value}"
        onChange={(e) => setF({ ...f, title_template: e.target.value })} />
      <label className="f" htmlFor="c-body-t">Body</label>
      <textarea id="c-body-t" value={f.body_template || ''} placeholder="{series} for {duration}. {summary} Runbook: https://wiki/…"
        onChange={(e) => setF({ ...f, body_template: e.target.value })} />
      <div className="hint">
        Leave empty for the default text. Placeholders:{' '}
        {(ph.data || []).map((p) => <code key={p.name} title={p.description} style={{ marginRight: 6 }}>{`{${p.name}}`}</code>)}
      </div>
      {(prev || err) && (
        <div style={{ marginTop: 10 }}>
          <div className="row" style={{ marginBottom: 6 }}><span className="muted">Preview</span><span className="right"><Seg value={kind} options={['firing', 'resolved']} onChange={setKind} /></span></div>
          {err ? <ErrorNote>{err}</ErrorNote> : (
            <div className="notice"><b>{prev.title}</b><div style={{ whiteSpace: 'pre-line' }}>{prev.body}</div></div>
          )}
        </div>
      )}
    </details>
  );
}

function ChannelModal({ channel, fields, onClose, onSaved }) {
  const { servers, multi } = useApp();
  const [scope, setScope] = useState((channel?.servers || []).join(', '));
  const [f, setF] = useState(channel || { name: '', type: 'slack', settings: {}, min_severity: 'warning', quiet_start: null, quiet_end: null, enabled: true });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const spec = fields?.[f.type] || [];
  const setS = (k, v) => setF({ ...f, settings: { ...f.settings, [k]: v } });
  const quiet = f.quiet_start != null && f.quiet_end != null;

  const save = async () => {
    setBusy(true); setErr(null);
    try { await api('/channels', { method: 'POST', body: { ...f, servers: scope.split(',').map((x) => x.trim()).filter(Boolean) } }); onSaved(); } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  return (
    <Modal title={channel ? `Edit ${channel.name}` : 'Add channel'} onClose={onClose} actions={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn primary" onClick={save} disabled={busy || !f.name}>Save</button>
    </>}>
      <label className="f" htmlFor="c-name">Name</label>
      <input id="c-name" type="text" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus />
      <label className="f" htmlFor="c-type">Type</label>
      <select id="c-type" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value, settings: {} })} disabled={!!channel}>
        {Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      {spec.map((s) => (
        <div key={s.key}>
          <label className="f" htmlFor={`c-${s.key}`}>{s.label}</label>
          <input id={`c-${s.key}`} type={s.secret ? 'password' : 'text'} autoComplete="off" value={f.settings[s.key] ?? ''} onChange={(e) => setS(s.key, e.target.value)} />
        </div>
      ))}
      <div className="hint">Tip: use <span className="mono">${'{ENV_VAR}'}</span> to read a secret from the server environment instead of storing it.</div>
      <label className="f" htmlFor="c-sev">Send</label>
      <select id="c-sev" value={f.min_severity} onChange={(e) => setF({ ...f, min_severity: e.target.value })}>{SEVS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      {multi && (
        <>
          <label className="f" htmlFor="c-scope">Only alerts from servers</label>
          <input id="c-scope" type="text" value={scope} onChange={(e) => setScope(e.target.value)} placeholder="all servers" />
          <div className="hint">Comma-separated ids ({servers.map((s) => s.id).join(', ')}), e.g. keep staging noise out of the on-call channel.</div>
        </>
      )}
      <label className="f row" style={{ gap: 8 }}><input type="checkbox" checked={quiet} onChange={(e) => setF({ ...f, quiet_start: e.target.checked ? 22 : null, quiet_end: e.target.checked ? 7 : null })} /> Quiet hours (critical alerts still come through)</label>
      {quiet && (
        <div className="row"><input type="number" min="0" max="23" value={f.quiet_start} onChange={(e) => setF({ ...f, quiet_start: Number(e.target.value) })} style={{ width: 80 }} aria-label="Quiet from hour" /><span>to</span>
          <input type="number" min="0" max="23" value={f.quiet_end} onChange={(e) => setF({ ...f, quiet_end: Number(e.target.value) })} style={{ width: 80 }} aria-label="Quiet until hour" /><span className="muted">server timezone, 24h</span></div>
      )}
      <MessageEditor f={f} setF={setF} />
      <div style={{ marginTop: 12 }}><ErrorNote>{err}</ErrorNote></div>
    </Modal>
  );
}

export default function Integrations() {
  const { can } = useApp();
  const chans = useApi('/channels', { interval: 20000 });
  const types = useApi('/channel-types');
  const [edit, setEdit] = useState(null);
  const [res, setRes] = useState({});
  const [digest, setDigest] = useState(null);

  const test = async (c) => {
    setRes((r) => ({ ...r, [c.id]: { busy: true } }));
    try { const r = await api(`/channels/${c.id}/test`, { method: 'POST' }); setRes((x) => ({ ...x, [c.id]: r })); chans.reload(); }
    catch (e) { setRes((x) => ({ ...x, [c.id]: { ok: false, error: e.message } })); }
  };
  const toggle = async (c, enabled) => { await api('/channels', { method: 'POST', body: { ...c, enabled } }); chans.reload(); };
  const del = async (c) => { if (window.confirm(`Delete channel "${c.name}"?`)) { await api(`/channels/${c.id}`, { method: 'DELETE' }); chans.reload(); } };
  const sendDigest = async () => { try { setDigest(await api('/digest/send', { method: 'POST' })); } catch (e) { setDigest({ error: e.message }); } };

  return (
    <div className="stack">
      <DiscoveryList />
      <div className="row wrap">
        <span className="muted">Where alerts and summaries are delivered.</span>
        {can.edit && <><button className="btn right" onClick={sendDigest}>Send summary now</button>
        <button className="btn primary" onClick={() => setEdit({})}>Add channel</button></>}
      </div>
      {digest && (digest.error ? <ErrorNote>{digest.error}</ErrorNote> : <div className="notice"><b>{digest.title}</b><div style={{ whiteSpace: 'pre-line' }}>{digest.body}</div></div>)}
      <ErrorNote>{chans.error}</ErrorNote>
      {chans.data && chans.data.length === 0 && <Card><Empty title="No channels yet">Add Slack, Teams, Telegram, email… to get notified when something breaks.</Empty></Card>}
      <div className="grid g2">
        {(chans.data || []).map((c) => {
          const r = res[c.id];
          return (
            <Card key={c.id} title={c.name} sub={TYPES[c.type]} actions={can.edit ? <Toggle checked={c.enabled} onChange={(v) => toggle(c, v)} label={`Enable ${c.name}`} /> : <Badge>{c.enabled ? 'on' : 'off'}</Badge>}>
              <div className="row wrap" style={{ marginBottom: 10 }}>
                <Badge kind="info">{SEVS.find((s) => s[0] === c.min_severity)?.[1]}</Badge>
                {c.servers?.length > 0 && <Badge kind="info">only: {c.servers.join(', ')}</Badge>}
                {(c.title_template || c.body_template) && <Badge>custom message</Badge>}
                {c.quiet_start != null && <Badge>quiet {c.quiet_start}:00–{c.quiet_end}:00</Badge>}
                {c.last_error ? <Badge kind="crit" icon="alert">last send failed</Badge> : c.last_sent_at ? <Badge kind="ok" icon="check">sent {fmtAgo(c.last_sent_at)}</Badge> : <Badge>never used</Badge>}
              </div>
              {c.last_error && <div className="err" style={{ marginBottom: 10 }}>{c.last_error}</div>}
              {r && !r.busy && (r.ok ? <div className="notice" style={{ marginBottom: 10 }}>Test message sent.</div> : <div className="err" style={{ marginBottom: 10 }}>{r.error}</div>)}
              {can.edit && <div className="row">
                <button className="btn sm" onClick={() => test(c)} disabled={r?.busy}>{r?.busy ? 'Sending…' : 'Send test'}</button>
                <button className="btn sm" onClick={() => setEdit(c)}>Edit</button>
                <button className="btn sm danger right" onClick={() => del(c)}>Delete</button>
              </div>}
            </Card>
          );
        })}
      </div>
      {edit && <ChannelModal channel={edit.id ? edit : null} fields={types.data} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); chans.reload(); }} />}
    </div>
  );
}
