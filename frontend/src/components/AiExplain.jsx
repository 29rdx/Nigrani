import { useEffect, useState } from 'react';
import { api } from '../api';
import { useApp } from '../ctx';
import { blocks } from '../mini';
import { fmtAgo } from '../format';
import { Card, ErrorNote, Icon } from './ui';

function Answer({ text }) {
  return (
    <div className="ai-text">
      {blocks(text).map((b, i) => {
        const kids = b.parts.map((p, n) => (p.b ? <b key={n}>{p.t}</b> : <span key={n}>{p.t}</span>));
        if (b.type === 'h') return <h4 key={i}>{kids}</h4>;
        if (b.type === 'li') return <div key={i} className="li"><span aria-hidden="true">•</span><span>{kids}</span></div>;
        return <p key={i}>{kids}</p>;
      })}
    </div>
  );
}

/** "Explain this incident": asks the assistant on demand; the answer is saved, so opening the page costs nothing. */
export default function AiExplain({ id }) {
  const { me, can } = useApp();
  const [saved, setSaved] = useState(null);     // null = not loaded yet
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!me.ai) return;
    setSaved(null); setErr(null);
    api(`/incidents/${encodeURIComponent(id)}/explain`).then((r) => setSaved(r.text ? r : {})).catch(() => setSaved({}));
  }, [id, me.ai]);

  if (!me.ai) return null;
  const ask = async (refresh) => {
    setBusy(true); setErr(null);
    try { setSaved(await api(`/incidents/${encodeURIComponent(id)}/explain${refresh ? '?refresh=true' : ''}`, { method: 'POST' })); } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const has = saved && saved.text;
  return (
    <Card title="AI explanation" sub={has ? `${saved.model} · ${fmtAgo(saved.generated_at)}` : 'what happened, the likely cause, what to check'}
      actions={has && can.edit ? <button className="btn sm" onClick={() => ask(true)} disabled={busy}>{busy ? 'Thinking…' : 'Regenerate'}</button> : null}>
      {has ? <Answer text={saved.text} /> : (
        <div className="row wrap">
          {can.edit
            ? <button className="btn primary" onClick={() => ask(false)} disabled={busy || saved === null}><Icon name="sparkle" size={15} />{busy ? 'Thinking…' : 'Explain this incident'}</button>
            : <span className="muted">Nobody has asked for an explanation yet. An editor can.</span>}
          <span className="muted">Sends this incident's metrics and context to the AI provider when you press the button.</span>
        </div>
      )}
      <ErrorNote>{err}</ErrorNote>
      {has && <div className="hint" style={{ marginTop: 10 }}>AI can be wrong. Check it against the charts above before acting.</div>}
    </Card>
  );
}
