import { useEffect, useRef, useState } from 'react';
import { Badge, Icon } from './ui';

const initials = (name) => (String(name || '?').split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join('') || '?').toUpperCase();

/** Account menu: who you are, theme, shortcuts, sign out. */
export default function UserMenu({ me, onAppearance, onHelp, onLogout }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc); };
  }, [open]);
  const name = me.name || me.user;
  const act = (fn) => () => { setOpen(false); fn(); };
  return (
    <div className="menu" ref={ref}>
      <button aria-haspopup="menu" aria-expanded={open} aria-label={`Account menu for ${name}`} onClick={() => setOpen(!open)}>
        <span className="avatar" aria-hidden="true">{initials(name)}</span>
      </button>
      {open && (
        <div className="menu-pop" role="menu">
          <div className="who-card">
            <div style={{ fontWeight: 650 }}>{name}</div>
            <div className="row" style={{ gap: 6, marginTop: 4 }}><Badge kind="info">{me.role}</Badge><span className="muted" style={{ fontSize: 12 }}>{me.provider === 'oidc' ? 'single sign-on' : me.provider === 'token' ? 'API token' : me.provider}</span></div>
          </div>
          <button role="menuitem" onClick={act(onAppearance)}><Icon name="sparkle" size={16} />Appearance</button>
          <button role="menuitem" onClick={act(onHelp)}><Icon name="file" size={16} />Keyboard shortcuts<kbd>?</kbd></button>
          {me.features.auth && <button role="menuitem" onClick={act(onLogout)}><Icon name="logout" size={16} />Sign out</button>}
        </div>
      )}
    </div>
  );
}
