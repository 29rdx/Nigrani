import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { Badge, Card, ErrorNote, Icon, Seg } from '../components/ui';
import { useApp } from '../ctx';

const KINDS = [['rules', 'Alert rules'], ['channels', 'Channels'], ['silences', 'Silences']];

function Plan({ plan }) {
  return (
    <div className="stack">
      <table className="t">
        <thead><tr><th><span className="sr">Kind</span></th><th>New</th><th>Overwritten</th><th>Skipped</th></tr></thead>
        <tbody>
          {KINDS.map(([k, label]) => {
            const s = plan.summary[k] || { create: 0, update: 0, skip: 0 };
            return <tr key={k}><td><b>{label}</b></td><td>{s.create}</td><td>{s.update}</td><td className="muted">{s.skip}</td></tr>;
          })}
        </tbody>
      </table>
      {plan.errors.length > 0 && (
        <div className="err" role="alert">
          <b>Nothing will be imported until this is fixed:</b>
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{plan.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
        </div>
      )}
      {plan.needs_secrets.length > 0 && (
        <div className="notice">
          <b>These channels are created disabled</b>, because their credentials are not in the file. Open Integrations,
          add the missing value and enable them:
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{plan.needs_secrets.map((n) => <li key={n.channel}><span className="mono">{n.channel}</span>: {n.keys.join(', ')}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

export default function Backup() {
  const { can } = useApp();
  const [withSecrets, setWithSecrets] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [fileName, setFileName] = useState('');
  const [data, setData] = useState(null);
  const [mode, setMode] = useState('merge');
  const [plan, setPlan] = useState(null);
  const [done, setDone] = useState(null);
  const input = useRef(null);

  const download = async () => {
    setError(null); setBusy(true);
    try {
      const res = await fetch(`/api/backup?include_secrets=${withSecrets}`, { credentials: 'same-origin' });
      if (!res.ok) throw new Error(`export failed (${res.status})`);
      const url = URL.createObjectURL(await res.blob());
      const a = Object.assign(document.createElement('a'), { href: url, download: `nigrani-backup-${new Date().toISOString().slice(0, 10)}.json` });
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  const check = async (payload, m) => {
    setError(null); setDone(null);
    try { setPlan(await api(`/backup/import?mode=${m}&dry_run=true`, { method: 'POST', body: payload })); }
    catch (e) { setPlan(null); setError(e.message); }
  };

  const pick = async (e) => {
    const file = e.target.files?.[0];
    setPlan(null); setDone(null); setData(null); setError(null);
    if (!file) return;
    setFileName(file.name);
    try { const parsed = JSON.parse(await file.text()); setData(parsed); await check(parsed, mode); }
    catch { setError('This file is not valid JSON.'); }
  };

  useEffect(() => { if (data) check(data, mode); }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps

  const apply = async () => {
    if (mode === 'overwrite' && !window.confirm('Overwrite existing rules and channels that have the same id as in the file?')) return;
    setBusy(true); setError(null);
    try {
      const res = await fetch(`/api/backup/import?mode=${mode}&dry_run=false`, {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'nigrani' }, body: JSON.stringify(data),
      });
      const body = await res.json();
      if (!res.ok && !body.errors) throw new Error(body.detail || `import failed (${res.status})`);
      setPlan(body); if (body.applied) setDone(body.summary);
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  const total = plan ? Object.values(plan.summary).reduce((n, s) => n + s.create + s.update, 0) : 0;

  return (
    <div className="grid g2">
      <Card title="Export" sub="rules, channels and silences">
        <p className="muted" style={{ marginTop: 0 }}>
          Everything you configured in the UI, as one JSON file: to move to a new server, keep a copy, or recover after a mistake.
          Incident history is not included.
        </p>
        {can.admin && <label className="row" style={{ gap: 8, margin: '12px 0' }}>
          <input type="checkbox" checked={withSecrets} onChange={(e) => setWithSecrets(e.target.checked)} />
          Include credentials (webhook URLs, tokens)
        </label>}
        {withSecrets
          ? <div className="err" role="alert">The file will contain working credentials. Store it like a password and never commit it.</div>
          : <div className="hint">Credentials are left out. Values that reference an environment variable, such as <span className="mono">${'{SLACK_URL}'}</span>, are kept because they are not secrets.</div>}
        <div style={{ marginTop: 14 }}>
          <button className="btn primary" onClick={download} disabled={busy}><Icon name="download" size={15} /> Download backup</button>
        </div>
      </Card>

      {can.admin ? <Card title="Restore" sub="from a backup file">
        <p className="muted" style={{ marginTop: 0 }}>
          Choose a file to see what would change first. Nothing is deleted, and if anything in the file is invalid nothing is imported.
        </p>
        <div className="row wrap" style={{ margin: '12px 0' }}>
          <button className="btn" onClick={() => input.current?.click()}><Icon name="upload" size={15} /> Choose backup file…</button>
          <input ref={input} type="file" accept="application/json,.json" onChange={pick} aria-label="Backup file" style={{ display: 'none' }} />
          {fileName && <span className="mono muted">{fileName}</span>}
        </div>
        <ErrorNote>{error}</ErrorNote>
        {data && plan && (
          <div className="stack" style={{ marginTop: 12 }}>
            <div className="row wrap">
              <span className="muted">If an id already exists:</span>
              <Seg value={mode} options={['merge', 'overwrite']} onChange={setMode} />
              <span className="hint">{mode === 'merge' ? 'keep what is here' : 'replace it with the file'}</span>
            </div>
            <Plan plan={plan} />
            {done ? <div className="notice"><Badge kind="ok" icon="check">Imported</Badge> {total} item{total === 1 ? '' : 's'} applied.</div>
              : <button className="btn primary" onClick={apply} disabled={busy || !plan.ok || total === 0}>{total === 0 ? 'Nothing to import' : `Import ${total} item${total === 1 ? '' : 's'}`}</button>}
          </div>
        )}
      </Card> : <Card title="Restore" sub="administrators only"><p className="muted" style={{ margin: 0 }}>Restoring a backup can overwrite rules and channels, so it needs the admin role.</p></Card>}
    </div>
  );
}
