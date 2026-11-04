import { useState } from 'react';
import { useApp } from '../ctx';
import { lsGet, lsSet } from '../format';
import { Card, Icon } from './ui';

/** First-run guidance for people who can change things: what is left to make Nigrani useful. Goes away when it is all done. */
export default function SetupChecklist({ o, disc, channels }) {
  const { me, can } = useApp();
  const [hidden, setHidden] = useState(() => lsGet('nigrani.setup.hidden', '') === '1');
  const steps = [
    { id: 'data', done: o.tiles.some((t) => t.value != null), title: 'Read metrics from Prometheus', text: 'Nigrani is reading them: the tiles above are live.' },
    { id: 'notify', done: (channels || []).some((c) => c.enabled), title: 'Get notified', text: 'Add Slack, Teams, Telegram, email or a webhook so alerts reach you.', href: '#/integrations', cta: 'Add a channel' },
    { id: 'presets', done: !(disc?.presets || []).some((p) => p.status === 'found'), title: 'Turn on what you run', text: 'Dashboards and alert rules for the services Nigrani found in your Prometheus.', href: '#/integrations', cta: 'See what it found' },
    { id: 'checks', done: (o.checks || []).length > 0, title: 'Watch your public endpoints', text: 'Add an uptime check for your website or API.', href: '#/uptime', cta: 'How to add one' },
  ];
  const left = steps.filter((s) => !s.done);
  if (!can.edit || me.demo || hidden || left.length === 0) return null;
  const done = steps.length - left.length;
  const hide = () => { lsSet('nigrani.setup.hidden', '1'); setHidden(true); };
  return (
    <Card title="Finish setting up Nigrani" sub={`${done} of ${steps.length} done`}
      actions={<button className="btn sm" onClick={hide} aria-label="Hide the setup checklist"><Icon name="x" size={13} /></button>}>
      <div className="setup-bar" role="progressbar" aria-valuemin="0" aria-valuemax={steps.length} aria-valuenow={done} aria-label="Setup progress"><i style={{ width: `${(done / steps.length) * 100}%` }} /></div>
      <ul className="setup-list">
        {steps.map((s) => (
          <li key={s.id} className={s.done ? 'done' : ''}>
            <span className="tick" aria-hidden="true">{s.done ? <Icon name="check" size={14} /> : null}</span>
            <div><b>{s.title}</b><span className="sr">{s.done ? ' (done)' : ' (to do)'}</span><div className="muted">{s.text}</div></div>
            {!s.done && s.href && <a className="btn sm right" href={s.href}>{s.cta}</a>}
          </li>
        ))}
      </ul>
    </Card>
  );
}
