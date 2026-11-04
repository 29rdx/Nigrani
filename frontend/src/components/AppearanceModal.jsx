import { ACCENTS, MODES } from '../appearance';
import { useApp } from '../ctx';
import { Modal } from './ui';

/** Colours and spacing. The page behind it changes as you choose, so you see the result straight away. */
export default function AppearanceModal({ onClose }) {
  const { mode, setMode, accent, setAccent, density, setDensity } = useApp();
  return (
    <Modal title="Appearance" onClose={onClose} actions={<button className="btn primary" onClick={onClose}>Done</button>}>
      <div className="ap-label" id="ap-mode">Mode</div>
      <div className="seg" role="radiogroup" aria-labelledby="ap-mode">
        {MODES.map(([id, label]) => <button key={id || 'system'} role="radio" aria-checked={mode === id} className={mode === id ? 'on' : ''} onClick={() => setMode(id)}>{label}</button>)}
      </div>
      <div className="ap-label" id="ap-accent">Accent colour</div>
      <div className="ap-swatches" role="radiogroup" aria-labelledby="ap-accent">
        {ACCENTS.map((a) => (
          <button key={a.id} role="radio" aria-checked={accent === a.id} className={`ap-swatch ${accent === a.id ? 'on' : ''}`} onClick={() => setAccent(a.id)}>
            <i style={{ background: a.swatch }} aria-hidden="true" />{a.label}
          </button>
        ))}
      </div>
      <div className="ap-label" id="ap-density">Spacing</div>
      <div className="seg" role="radiogroup" aria-labelledby="ap-density">
        {[['comfortable', 'Comfortable'], ['compact', 'Compact']].map(([id, label]) => <button key={id} role="radio" aria-checked={density === id} className={density === id ? 'on' : ''} onClick={() => setDensity(id)}>{label}</button>)}
      </div>
      <div className="hint" style={{ marginTop: 14 }}>Saved in this browser. Status colours (green, amber, red) stay the same in every accent, so an alert always looks like an alert.</div>
    </Modal>
  );
}
