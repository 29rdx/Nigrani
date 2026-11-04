import { useEffect, useState } from 'react';
import { api } from '../api';
import Logo from '../components/Logo';
import { ErrorNote } from '../components/ui';

export default function Login({ onDone }) {
  const [u, setU] = useState('');
  const [p, setP] = useState('');
  const [err, setErr] = useState(new URLSearchParams(window.location.search).get('sso_error'));
  const [busy, setBusy] = useState(false);
  const [sso, setSso] = useState(null);
  const [show, setShow] = useState(false);

  useEffect(() => {
    api('/auth/config').then((c) => setSso(c.oidc)).catch(() => {});
    if (new URLSearchParams(window.location.search).has('sso_error')) window.history.replaceState({}, '', window.location.pathname + window.location.hash);
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { await api('/login', { method: 'POST', body: { username: u, password: p } }); onDone(); }
    catch (x) { setErr(x.message); }
    setBusy(false);
  };

  return (
    <main className="login">
      <form className="card" onSubmit={submit} aria-labelledby="login-title">
        <div className="login-head"><Logo size={44} /><h1 id="login-title">Sign in to Nigrani</h1><p className="muted">Watching your services, so you don’t have to.</p></div>
        {sso && (
          <>
            <a className="btn primary sso" href={sso.login_url}>{sso.label}</a>
            <div className="divider">or with a password</div>
          </>
        )}
        <label className="f" htmlFor="u">Username</label>
        <input id="u" type="text" value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" autoFocus={!sso} />
        <label className="f" htmlFor="p">Password</label>
        <div className="pw">
          <input id="p" type={show ? 'text' : 'password'} value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" />
          <button type="button" className="btn sm" onClick={() => setShow(!show)} aria-pressed={show}>{show ? 'Hide' : 'Show'}</button>
        </div>
        <div style={{ marginTop: 12 }}><ErrorNote>{err}</ErrorNote></div>
        <button className="btn primary" style={{ width: '100%', justifyContent: 'center', marginTop: 16 }} disabled={busy || !p || !u}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </main>
  );
}
