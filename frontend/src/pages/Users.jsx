import { useState } from 'react';
import { api, useApi } from '../api';
import ApiTokens from '../components/ApiTokens';
import { Badge, Card, ErrorNote, Modal, Toggle } from '../components/ui';
import { useApp } from '../ctx';
import { fmtAgo } from '../format';

const ROLES = [['viewer', 'Viewer: can look, cannot change anything'], ['editor', 'Editor: alerts, channels, silences, acknowledge'], ['admin', 'Admin: everything, including users and restoring backups']];

function UserModal({ user, onClose, onSaved }) {
  const editing = !!user;
  const [f, setF] = useState(user ? { name: user.name, email: user.email || '', role: user.role, password: '' } : { username: '', name: '', email: '', role: 'viewer', password: '' });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const canPassword = !editing || user.provider === 'local';
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      if (editing) {
        const body = { name: f.name, email: f.email || null, role: f.role };
        if (f.password) body.password = f.password;
        await api(`/users/${user.id}`, { method: 'PUT', body });
      } else {
        await api('/users', { method: 'POST', body: { ...f, email: f.email || null } });
      }
      onSaved();
    } catch (e) { setErr(e.message); setBusy(false); }
  };
  return (
    <Modal title={editing ? `Edit ${user.username}` : 'Add user'} onClose={onClose} actions={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn primary" onClick={save} disabled={busy || (!editing && (!f.username || !f.password))}>Save</button>
    </>}>
      {!editing && <><label className="f" htmlFor="u-name">Username</label><input id="u-name" type="text" value={f.username} onChange={set('username')} autoFocus autoComplete="off" /></>}
      <label className="f" htmlFor="u-disp">Display name</label>
      <input id="u-disp" type="text" value={f.name} onChange={set('name')} />
      <label className="f" htmlFor="u-mail">E-mail (optional)</label>
      <input id="u-mail" type="text" value={f.email} onChange={set('email')} />
      <label className="f" htmlFor="u-role">Role</label>
      <select id="u-role" value={f.role} onChange={set('role')}>{ROLES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      {canPassword && (
        <>
          <label className="f" htmlFor="u-pw">{editing ? 'New password (leave empty to keep)' : 'Password'}</label>
          <input id="u-pw" type="password" value={f.password} onChange={set('password')} autoComplete="new-password" />
          <div className="hint">At least 10 characters.</div>
        </>
      )}
      <div style={{ marginTop: 12 }}><ErrorNote>{err}</ErrorNote></div>
    </Modal>
  );
}

export default function Users() {
  const { me } = useApp();
  const { data, error, reload } = useApi('/users', { interval: 30000 });
  const [edit, setEdit] = useState(null);
  const [problem, setProblem] = useState(null);
  const guard = async (fn) => { setProblem(null); try { await fn(); reload(); } catch (e) { setProblem(e.message); } };
  const toggle = (u, disabled) => guard(() => api(`/users/${u.id}`, { method: 'PUT', body: { disabled } }));
  const del = (u) => window.confirm(`Delete ${u.username}?`) && guard(() => api(`/users/${u.id}`, { method: 'DELETE' }));
  return (
    <div className="stack">
      <div className="row">
        <span className="muted">Who can sign in, and what they can do. People who sign in with single sign-on appear here after their first visit.</span>
        <button className="btn primary right" onClick={() => setEdit({})}>Add user</button>
      </div>
      <ErrorNote>{error || problem}</ErrorNote>
      <Card flush>
        <div className="scroll"><table className="t">
          <thead><tr><th>User</th><th>Role</th><th>Sign-in</th><th>Last seen</th><th>Active</th><th /></tr></thead>
          <tbody>{(data || []).map((u) => {
            const config = u.provider === 'config';
            const self = u.username === me.user;
            return (
              <tr key={u.username}>
                <td><b>{u.name || u.username}</b>{u.name && u.name !== u.username && <div className="muted mono" style={{ fontSize: 12 }}>{u.username}</div>}{self && <Badge kind="info">you</Badge>}</td>
                <td><Badge kind={u.role === 'admin' ? 'crit' : u.role === 'editor' ? 'warn' : ''}>{u.role}</Badge></td>
                <td>{config ? <span className="muted">configured admin (cannot be edited)</span> : u.provider === 'oidc' ? 'single sign-on' : 'password'}</td>
                <td className="muted">{u.last_login ? fmtAgo(u.last_login) : 'never'}</td>
                <td>{config ? <Badge kind="ok" icon="check">always</Badge> : <Toggle checked={!u.disabled} onChange={(v) => toggle(u, !v)} label={`${u.username} can sign in`} />}</td>
                <td style={{ whiteSpace: 'nowrap' }}>{!config && <><button className="btn sm" onClick={() => setEdit(u)}>Edit</button> <button className="btn sm danger" onClick={() => del(u)} disabled={self}>Delete</button></>}</td>
              </tr>
            );
          })}</tbody>
        </table></div>
      </Card>
      <ApiTokens />
      {edit && <UserModal user={edit.id ? edit : null} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); }} />}
    </div>
  );
}
