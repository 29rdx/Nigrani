import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, setCurrentServer, useApi, useConnectionLost, useHashRoute } from './api';
import CommandPalette from './components/CommandPalette';
import ErrorBoundary from './components/ErrorBoundary';
import Logo from './components/Logo';
import ShortcutsHelp from './components/ShortcutsHelp';
import { PageSkeleton } from './components/Skeleton';
import { ToastProvider, useToast } from './components/Toast';
import UserMenu from './components/UserMenu';
import { Icon, Seg } from './components/ui';
import { gotoRoute, isTyping } from './palette';
import { cleanAccent, cleanMode, resolveMode } from './appearance';
import { faviconHref, pageTitle } from './brand';
import AppearanceModal from './components/AppearanceModal';
import { AppCtx, useApp } from './ctx';
import { lsGet, lsSet } from './format';
const Alerts = page(() => import('./pages/Alerts'));
const Backup = page(() => import('./pages/Backup'));
const Containers = page(() => import('./pages/Containers'));
const Deploys = page(() => import('./pages/Deploys'));
const Fleet = page(() => import('./pages/Fleet'));
const Host = page(() => import('./pages/Host'));
const Audit = page(() => import('./pages/Audit'));
const Incident = page(() => import('./pages/Incident'));
const Integrations = page(() => import('./pages/Integrations'));
const Login = page(() => import('./pages/Login'));
const Logs = page(() => import('./pages/Logs'));
const Overview = page(() => import('./pages/Overview'));
const PanelPage = page(() => import('./pages/PanelPage'));
const Sentry = page(() => import('./pages/Sentry'));
const ArgoCD = page(() => import('./pages/ArgoCD'));
const SLOs = page(() => import('./pages/SLOs'));
const Kubernetes = page(() => import('./pages/Kubernetes'));
const Datadog = page(() => import('./pages/Datadog'));
const Status = page(() => import('./pages/Status'));
const Uptime = page(() => import('./pages/Uptime'));
const Users = page(() => import('./pages/Users'));

/** A lazily loaded page whose chunk can also be fetched ahead of time (at start-up, and when a menu item is hovered). */
function page(loader) {
  const C = lazy(loader);
  C.preload = loader;
  return C;
}
const PRELOAD = { '': Overview, overview: Overview, containers: Containers, host: Host, alerts: Alerts, incident: Incident, uptime: Uptime, integrations: Integrations, p: PanelPage, slos: SLOs, logs: Logs, deploys: Deploys, users: Users, fleet: Fleet };
const warm = (key) => PRELOAD[key]?.preload?.();
if (typeof window !== 'undefined') warm(window.location.hash.replace(/^#\//, '').split('/')[0]);   // fetch this page's code while we check who is signed in

// Ask who is signed in as soon as the script runs, in parallel with React starting up.
let firstMe = typeof window !== 'undefined' && !window.location.hash.startsWith('#/status') ? api('/me').catch(() => false) : null;

/** What shows while we find out who is signed in: the real shell's outline, so the page does not appear from nothing. */
function BootShell() {
  return (
    <div className="app" role="status" aria-label="Loading">
      <aside className="side"><div className="brand"><Logo size={28} />Nigrani</div>
        <div className="stack" aria-hidden="true" style={{ padding: '4px 8px' }}>{Array.from({ length: 7 }, (_, i) => <i key={i} className="skel" style={{ height: 30, width: `${60 + (i % 3) * 12}%` }} />)}</div></aside>
      <div className="main"><header className="top"><h1>Overview</h1></header><main className="content"><PageSkeleton /></main></div>
    </div>
  );
}

const RANGES = ['15m', '1h', '6h', '24h', '7d'];

/** Mode (system / light / dark) and accent colour. The <html> attributes are what the CSS reads; theme-init.js sets them before the first paint. */
function useAppearance() {
  const media = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  const [mode, setModeState] = useState(() => cleanMode(document.documentElement.dataset.theme || lsGet('nigrani.theme', '')));   // theme-init.js already read the address and storage
  const [accent, setAccentState] = useState(() => cleanAccent(document.documentElement.dataset.accent || lsGet('nigrani.accent', '')));
  const [sys, setSys] = useState(media ? media.matches : false);
  useEffect(() => {
    if (!media) return undefined;
    const on = (e) => setSys(e.matches);
    media.addEventListener('change', on);
    return () => media.removeEventListener('change', on);
  }, [media]);
  const theme = resolveMode(mode, sys);
  useEffect(() => { if (mode) document.documentElement.dataset.theme = mode; else delete document.documentElement.dataset.theme; }, [mode]);
  useEffect(() => { document.documentElement.dataset.accent = accent; }, [accent]);
  const setMode = (m) => { const c = cleanMode(m); setModeState(c); lsSet('nigrani.theme', c); };
  const setAccent = (id) => { const c = cleanAccent(id); setAccentState(c); lsSet('nigrani.accent', c); };
  const toggle = () => setMode(theme === 'dark' ? 'light' : 'dark');
  return { theme, mode, setMode, accent, setAccent, toggle };
}

function Shell({ me, onLogout }) {
  const [range, setRangeState] = useState(() => (RANGES.includes(lsGet('nigrani.range', '')) ? lsGet('nigrani.range', '1h') : '1h'));
  const look = useAppearance();
  const { theme, toggle: toggleTheme } = look;
  const [density, setDensityState] = useState(() => lsGet('nigrani.density', 'comfortable'));
  useEffect(() => { document.documentElement.dataset.density = density; }, [density]);
  const setDensity = (d) => { setDensityState(d); lsSet('nigrani.density', d); };
  const [server, setServerState] = useState(() => {
    const saved = lsGet('nigrani.server', '');
    return me.servers.some((s) => s.id === saved) ? saved : me.default_server;
  });
  setCurrentServer(server); // keep imperative api() calls pointed at the selected server
  const setServer = (id) => { setCurrentServer(id); setServerState(id); lsSet('nigrani.server', id); };
  const multi = me.servers.length > 1;
  const ctx = useMemo(() => ({ range, theme, mode: look.mode, setMode: look.setMode, accent: look.accent, setAccent: look.setAccent, look: `${theme}:${look.accent}`, density, setDensity, me, can: me.can || { edit: false, admin: false }, server, servers: me.servers, multi, setServer }), [range, theme, look.mode, look.accent, density, me, server, multi]); // eslint-disable-line react-hooks/exhaustive-deps
  const setRange = (r) => { setRangeState(r); lsSet('nigrani.range', r); };
  return (
    <AppCtx.Provider value={ctx}>
      <Layout me={me} onLogout={onLogout} toggleTheme={toggleTheme} setRange={setRange} />
    </AppCtx.Provider>
  );
}

// Everything below the provider, so its useApi() calls follow the selected server.
function Layout({ me, onLogout, toggleTheme, setRange }) {
  const { range, theme, accent, density, setDensity, server, setServer, multi } = useApp();
  const route = useHashRoute();
  const [open, setOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const [appearance, setAppearance] = useState(false);
  const lost = useConnectionLost();
  const toast = useToast();
  const cur = me.servers.find((s) => s.id === server) || me.servers[0];
  const pages = useApi('/pages', { interval: 60000 });
  const firing = useApi('/incidents?status=firing', { interval: 20000 });

  useEffect(() => { setOpen(false); }, [route]);
  useEffect(() => {
    const back = () => toast.ok('Connection restored');
    window.addEventListener('nigrani:reconnected', back);
    return () => window.removeEventListener('nigrani:reconnected', back);
  }, [toast]);
  const goRef = useRef({ armed: 0 });
  useEffect(() => {                                   // Ctrl/Cmd+K or / = search, ? = help, "g" then a letter = go to a page
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((p) => !p); return; }
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target) || palette || help) return;
      if (e.key === '/') { e.preventDefault(); setPalette(true); return; }
      if (e.key === '?') { e.preventDefault(); setHelp(true); return; }
      const now = Date.now();
      if (e.key.toLowerCase() === 'g') { goRef.current.armed = now; return; }
      if (goRef.current.armed && now - goRef.current.armed < 1200) {
        const to = gotoRoute(e.key);
        goRef.current.armed = 0;
        if (to) { e.preventDefault(); window.location.hash = to; }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [palette, help]);
  useEffect(() => {                                                    // a preset was turned on or off (Discovery)
    const refresh = () => { pages.reload(); };
    window.addEventListener('nigrani:presets', refresh);
    return () => window.removeEventListener('nigrani:presets', refresh);
  }, [pages.reload]);

  const [, section, sub] = route.split('/');
  const nav = useMemo(() => {
    const items = [
      ...(multi ? [{ to: '/fleet', label: 'All servers', icon: 'layers', key: 'fleet' }] : []),
      { to: '/overview', label: 'Overview', icon: 'grid', key: 'overview' },
      { to: '/containers', label: 'Containers', icon: 'box', key: 'containers' },
      { to: '/host', label: 'Host', icon: 'server', key: 'host' },
    ];
    const extra = (pages.data || []).map((p) => ({ to: `/p/${p.id}`, label: p.title, icon: p.icon, key: `p/${p.id}`, dim: !p.available }));
    const tail = [
      ...(cur.logs ? [{ to: '/logs', label: 'Logs', icon: 'file', key: 'logs' }] : []),
      ...(cur.datadog ? [{ to: '/datadog', label: 'Datadog', icon: 'pulse', key: 'datadog' }] : []),
      ...(cur.slo ? [{ to: '/slos', label: 'SLOs', icon: 'chart', key: 'slos' }] : []),
      ...(cur.argocd ? [{ to: '/argocd', label: 'Argo CD', icon: 'rocket', key: 'argocd' }] : []),
      ...(cur.kubernetes ? [{ to: '/kubernetes', label: 'Kubernetes', icon: 'layers', key: 'kubernetes' }] : []),
      ...(cur.sentry ? [{ to: '/sentry', label: 'Sentry', icon: 'bug', key: 'sentry' }] : []),
      { to: '/alerts/active', label: 'Alerts', icon: 'bell', key: 'alerts', count: firing.data?.length || 0 },
      { to: '/uptime', label: 'Uptime', icon: 'shield', key: 'uptime' },
      ...(cur.deploys ? [{ to: '/deploys', label: 'Deploys', icon: 'rocket', key: 'deploys' }] : []),
      { to: '/integrations', label: 'Integrations', icon: 'plug', key: 'integrations' },
      { to: '/backup', label: 'Backup', icon: 'download', key: 'backup' },
      ...(me.can?.admin ? [{ to: '/users', label: 'Users', icon: 'users', key: 'users' }, { to: '/audit', label: 'Audit log', icon: 'file', key: 'audit' }] : []),
    ];
    return { items, extra, tail };
  }, [pages.data, firing.data, cur, multi]);

  const current = section === 'p' ? `p/${sub}` : section === 'incident' ? 'alerts' : section;
  const all = [...nav.items, ...nav.extra, ...nav.tail];
  const title = section === 'incident' ? 'Incident' : (all.find((n) => n.key === current)?.label || 'Overview');
  const firingCount = firing.data?.length || 0;
  useEffect(() => { document.title = pageTitle(firingCount, title, me.app); }, [firingCount, title, me.app]);
  useEffect(() => {                                       // a red dot on the favicon while something is firing
    const link = document.querySelector('link[rel="icon"]');
    if (link) { link.type = 'image/svg+xml'; link.href = faviconHref(firingCount, accent); }
  }, [firingCount, accent]);

  let view;
  switch (section) {
    case 'fleet': view = <Fleet />; break;
    case 'containers': view = <Containers />; break;
    case 'host': view = <Host />; break;
    case 'p': view = <PanelPage key={sub} id={sub} />; break;
    case 'logs': view = <Logs />; break;
    case 'sentry': view = <Sentry />; break;
    case 'kubernetes': view = <Kubernetes />; break;
    case 'argocd': view = <ArgoCD />; break;
    case 'slos': view = <SLOs />; break;
    case 'datadog': view = <Datadog />; break;
    case 'alerts': view = <Alerts tab={sub || 'active'} />; break;
    case 'incident': view = <Incident key={sub} id={sub} />; break;
    case 'uptime': view = <Uptime />; break;
    case 'deploys': view = <Deploys />; break;
    case 'integrations': view = <Integrations />; break;
    case 'backup': view = <Backup />; break;
    case 'users': view = <Users />; break;
    case 'audit': view = <Audit />; break;
    default: view = <Overview />;
  }

  const link = (n) => (
    <a key={n.key} href={`#${n.to}`} onMouseEnter={() => warm(n.key.split('/')[0])} onFocus={() => warm(n.key.split('/')[0])} className={`${current === n.key ? 'active' : ''} ${n.dim ? 'dim' : ''}`} aria-current={current === n.key ? 'page' : undefined}>
      <Icon name={n.icon} />{n.label}{n.count > 0 && <span className="count" aria-label={`${n.count} firing`}>{n.count}</span>}
    </a>
  );

  return (
    <>
      {me.demo && <div className="demo-bar" role="note"><Icon name="sparkle" size={14} /> Demo: sample data, read-only. <a href="https://github.com/nikhilrai-tech/Nigrani#readme" target="_blank" rel="noopener noreferrer">Run your own in one command</a></div>}
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus(); }}>Skip to content</a>
      {lost && <div className="conn" role="alert"><Icon name="alert" size={16} /> Can’t reach Nigrani. Retrying…</div>}
      <div className="app">
        <aside className={`side ${open ? 'open' : ''}`}>
          <div className="brand"><Logo size={28} />{me.app}</div>
          <nav className="nav" aria-label="Main">
            {nav.items.map(link)}
            {nav.extra.length > 0 && <div className="group">Services</div>}
            {nav.extra.map(link)}
            <div className="group">Operate</div>
            {nav.tail.map(link)}
          </nav>
          <div className="foot">
            <button className="btn sm" onClick={() => setPalette(true)} style={{ justifyContent: 'space-between' }}><span>Search</span><kbd>Ctrl K</kbd></button>
            <div className="row"><span>Nigrani v{me.version}</span><a href="https://github.com/nikhilrai-tech/Nigrani" target="_blank" rel="noopener noreferrer">GitHub</a></div>
          </div>
        </aside>
        <div className="main">
          <header className="top">
            <button className="btn icon menu-btn" onClick={() => setOpen(!open)} aria-label="Menu"><Icon name="menu" /></button>
            <h1>{title}</h1>
            {multi ? (
              <select className="server-pick" value={server} onChange={(e) => setServer(e.target.value)} aria-label="Server">
                {me.servers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            ) : <span className="badge info">{cur.environment}</span>}
            <span className="spacer" />
            {['overview', 'host', 'p', 'containers'].includes(section || 'overview') && <Seg value={range} options={RANGES} onChange={setRange} />}
            <button className="search-btn" onClick={() => setPalette(true)} aria-label="Search (Ctrl K)"><Icon name="search" size={15} /><span>Search…</span><kbd>Ctrl K</kbd></button>
            <button className="btn icon" onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}><Icon name={theme === 'dark' ? 'sun' : 'moon'} /></button>
            <UserMenu me={me} onAppearance={() => setAppearance(true)} onHelp={() => setHelp(true)} onLogout={onLogout} />
          </header>
          <main id="main" tabIndex={-1} className="content" key={server}>
            <ErrorBoundary key={route}><Suspense fallback={<PageSkeleton />}>{view}</Suspense></ErrorBoundary>
          </main>
        </div>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)}
        pages={all.map((n) => ({ label: n.label, to: n.to, hint: n.key }))}
        actions={[{ label: theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme', run: toggleTheme }, { label: 'Appearance: colours and spacing', run: () => setAppearance(true) }, { label: 'Keyboard shortcuts', run: () => setHelp(true) },
          ...(me.features.auth ? [{ label: 'Sign out', run: onLogout }] : [])]} />
      {help && <ShortcutsHelp onClose={() => setHelp(false)} />}
      {appearance && <AppearanceModal onClose={() => setAppearance(false)} />}
    </>
  );
}

export default function App() {
  const route = useHashRoute();
  const [me, setMe] = useState(undefined); // undefined = loading, false = signed out

  const loadMe = useCallback(async () => {
    try {
      const early = firstMe; firstMe = null;                      // the request started at load, if there is one
      const who = early ? await early : await api('/me');
      setMe(who || false);
    } catch { setMe(false); }
  }, []);
  useEffect(() => {
    loadMe();
    const refresh = setInterval(() => { api('/me').then(setMe).catch(() => {}); }, 30000);   // roles can change while you are signed in
    const onForbidden = () => { api('/me').then(setMe).catch(() => {}); };
    window.addEventListener('nigrani:forbidden', onForbidden);
    const on = () => setMe(false);
    window.addEventListener('nigrani:unauth', on);
    return () => {
      clearInterval(refresh);
      window.removeEventListener('nigrani:unauth', on);
      window.removeEventListener('nigrani:forbidden', onForbidden);
    };
  }, [loadMe]);

  if (route.startsWith('/status')) return <Suspense fallback={<div className="pub"><PageSkeleton /></div>}><Status /></Suspense>;
  if (me === undefined) return <BootShell />;
  if (me === false) return <Suspense fallback={<div className="login"><Logo size={44} /></div>}><Login onDone={loadMe} /></Suspense>;
  return (
    <ToastProvider>
      <Shell me={me} onLogout={async () => { await api('/logout', { method: 'POST' }); setMe(false); }} />
    </ToastProvider>
  );
}
