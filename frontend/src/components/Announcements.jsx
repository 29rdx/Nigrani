import { useState } from 'react';
import { api, useApi } from '../api';
import { useApp } from '../ctx';
import { Announcement } from '../pages/Status';
import { Card, Empty, ErrorNote, Icon } from './ui';

const toTs = (v) => (v ? new Date(v).getTime() / 1000 : null);

/** Post updates to the public status page: incidents you are working on, planned maintenance, notices. */
export default function Announcements() {
  const { can } = useApp();
  const { data, reload } = useApi('/announcements', { interval: 30000 });
  const [f, setF] = useState({ kind: 'incident', title: '', body: '', starts: '', ends: '' });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const post = async () => {
    setErr(null); setBusy(true);
    try {
      await api('/announcements', { method: 'POST', body: { kind: f.kind, title: f.title, body: f.body, starts_at: toTs(f.starts), ends_at: toTs(f.ends) } });
      setF({ ...f, title: '', body: '', starts: '', ends: '' });
      reload();
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const act = async (path, method) => { try { await api(path, { method }); reload(); } catch (e) { setErr(e.message); } };
  return (
    <Card title="Status page updates" sub="shown on the public status page (#/status)" flush>
      {can.edit && (
        <div className="stack" style={{ padding: 14 }}>
          <div className="row wrap">
            <select aria-label="Type" value={f.kind} onChange={set('kind')}>
              <option value="incident">Incident</option><option value="maintenance">Maintenance</option><option value="info">Notice</option>
            </select>
            <input type="text" aria-label="Title" style={{ flex: 1, minWidth: 180 }} placeholder="Title, e.g. Slow logins" value={f.title} onChange={set('title')} maxLength={120} />
          </div>
          <textarea aria-label="Details" rows={2} placeholder="What people should know (optional)" value={f.body} onChange={set('body')} maxLength={2000} />
          <div className="row wrap">
            <label className="muted">Starts <input type="datetime-local" value={f.starts} onChange={set('starts')} /></label>
            <label className="muted">Ends <input type="datetime-local" value={f.ends} onChange={set('ends')} /></label>
            <button className="btn primary right" onClick={post} disabled={busy || !f.title.trim()}><Icon name="plus" size={15} />Post update</button>
          </div>
          <div className="hint">Leave the times empty to publish it now. Planned maintenance with a start time in the future shows as scheduled.</div>
          <ErrorNote>{err}</ErrorNote>
        </div>
      )}
      {!data || data.length === 0 ? <Empty title="No updates posted" /> : (
        <div className="list">{data.map((a) => (
          <div key={a.id} className="row" style={{ alignItems: 'flex-start' }}>
            <div style={{ flex: 1, minWidth: 0 }}><Announcement a={a} /></div>
            {can.edit && (
              <div className="row" style={{ gap: 6 }}>
                {!a.resolved_at && <button className="btn sm" onClick={() => act(`/announcements/${a.id}/resolve`, 'POST')}>Resolve</button>}
                <button className="btn sm" aria-label={`Delete ${a.title}`} onClick={() => act(`/announcements/${a.id}`, 'DELETE')}><Icon name="trash" size={13} /></button>
              </div>
            )}
          </div>))}</div>
      )}
    </Card>
  );
}
