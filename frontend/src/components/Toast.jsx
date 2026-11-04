import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import { Icon } from './ui';

const Ctx = createContext({ ok: () => {}, err: () => {}, info: () => {}, run: async (fn) => fn() });
export const useToast = () => useContext(Ctx);

/** Short confirmations for actions ("Rule saved") and failures, announced to screen readers. */
export function ToastProvider({ children }) {
  const [list, setList] = useState([]);
  const seq = useRef(0);
  const drop = useCallback((id) => setList((l) => l.filter((t) => t.id !== id)), []);
  const push = useCallback((kind, text, ms) => {
    seq.current += 1;
    const id = seq.current;
    setList((l) => [...l.slice(-3), { id, kind, text }]);
    setTimeout(() => drop(id), ms ?? (kind === 'err' ? 7000 : 3500));
  }, [drop]);
  const api = useMemo(() => ({
    ok: (t, ms) => push('ok', t, ms), err: (t, ms) => push('err', t, ms), info: (t, ms) => push('info', t, ms),
    /** Run an action: confirm it with a toast, or say what went wrong instead of failing silently. */
    run: async (fn, okText) => { try { const r = await fn(); if (okText) push('ok', okText); return r; } catch (e) { push('err', e.message || 'Something went wrong'); return undefined; } },
  }), [push]);
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {list.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <Icon name={t.kind === 'ok' ? 'check' : t.kind === 'err' ? 'alert' : 'activity'} size={16} />
            <span>{t.text}</span>
            <button className="x" onClick={() => drop(t.id)} aria-label="Dismiss"><Icon name="x" size={14} /></button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
