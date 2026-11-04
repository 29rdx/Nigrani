import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';
import { fmtAgo } from '../format';
import { rank } from '../palette';
import { Icon } from './ui';

const ICON = { Pages: 'grid', Actions: 'sparkle', Alerts: 'bell', Rules: 'edit', Containers: 'box' };

/** Ctrl/Cmd+K: jump to any page, alert, rule or container, or run an action, from the keyboard. */
export default function CommandPalette({ open, onClose, pages, actions }) {
  const [q, setQ] = useState('');
  const [sel, setSel] = useState(0);
  const [dyn, setDyn] = useState([]);
  const input = useRef(null);
  const list = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    setQ(''); setSel(0);
    setTimeout(() => input.current?.focus(), 0);
    let live = true;
    Promise.all([api('/incidents?status=all&days=7&limit=30').catch(() => []), api('/rules').catch(() => []), api('/containers').catch(() => [])])
      .then(([inc, rules, cont]) => {
        if (!live) return;
        setDyn([
          ...inc.map((i) => ({ group: 'Alerts', label: i.rule_name + (i.series ? ` · ${i.series}` : ''), hint: `${i.status}, ${fmtAgo(i.started_at)}`, to: `/incident/${i.id}` })),
          ...rules.map((r) => ({ group: 'Rules', label: r.name, hint: r.datasource, to: '/alerts/rules' })),
          ...cont.map((c) => ({ group: 'Containers', label: c.name, hint: c.up ? 'running' : 'down', to: '/containers' })),
        ]);
      });
    return () => { live = false; };
  }, [open]);

  const items = useMemo(() => {
    const ranked = rank([...pages.map((p) => ({ ...p, group: 'Pages' })), ...actions.map((a) => ({ ...a, group: 'Actions' })), ...dyn], q, 40);
    const order = [];                                          // keep each group together, the group with the best match first
    ranked.forEach((it) => { if (!order.includes(it.group)) order.push(it.group); });
    return [...ranked].sort((a, b) => order.indexOf(a.group) - order.indexOf(b.group));
  }, [pages, actions, dyn, q]);
  useEffect(() => { setSel(0); }, [q]);
  useEffect(() => { list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' }); }, [sel]);
  if (!open) return null;

  const run = (it) => { onClose(); if (it.to) window.location.hash = it.to; else if (it.run) it.run(); };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(items.length - 1, s + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(0, s - 1)); }
    else if (e.key === 'Enter' && items[sel]) { e.preventDefault(); run(items[sel]); }
  };
  let last = '';
  return (
    <div className="pal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="pal" role="dialog" aria-modal="true" aria-label="Command palette" onKeyDown={onKey}>
        <input ref={input} type="text" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search pages, alerts, rules, containers…"
          role="combobox" aria-expanded="true" aria-controls="pal-list" aria-activedescendant={items[sel] ? `pal-${sel}` : undefined} aria-label="Search" autoComplete="off" spellCheck={false} />
        <div className="pal-list" id="pal-list" role="listbox" ref={list}>
          {items.length === 0 && <div className="empty" style={{ padding: 24 }}>Nothing matches “{q}”.</div>}
          {items.map((it, i) => {
            const head = it.group !== last ? <div className="pal-group" role="presentation">{it.group}</div> : null;
            last = it.group;
            return (
              <div key={`${it.group}-${i}`}>
                {head}
                <div id={`pal-${i}`} role="option" aria-selected={i === sel} className="pal-item" onMouseMove={() => setSel(i)} onClick={() => run(it)}>
                  <Icon name={ICON[it.group] || 'chart'} size={16} /><span>{it.label}</span>{it.hint && <span className="hint">{it.hint}</span>}
                </div>
              </div>
            );
          })}
        </div>
        <div className="pal-foot"><span><kbd>↑</kbd> <kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span></div>
      </div>
    </div>
  );
}
