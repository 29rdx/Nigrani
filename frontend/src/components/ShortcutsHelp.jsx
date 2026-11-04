import { Modal } from './ui';

const ROWS = [
  [['Ctrl', 'K'], 'Search pages, alerts, rules and containers (also /)'],
  [['g', 'o'], 'Go to Overview'], [['g', 'a'], 'Go to Alerts'], [['g', 'c'], 'Go to Containers'], [['g', 'h'], 'Go to Host'],
  [['g', 'u'], 'Go to Uptime'], [['g', 'i'], 'Go to Integrations'], [['g', 'd'], 'Go to Deploys'], [['g', 's'], 'Go to SLOs'],
  [['?'], 'Show this list'],
];

export default function ShortcutsHelp({ onClose }) {
  return (
    <Modal title="Keyboard shortcuts" onClose={onClose} actions={<button className="btn primary" onClick={onClose}>Close</button>}>
      <div className="help-grid" style={{ marginTop: 10 }}>
        {ROWS.map(([keys, what]) => (
          <div key={what} style={{ display: 'contents' }}>
            <span className="row" style={{ gap: 4 }}>{keys.map((k, i) => <span key={k} className="row" style={{ gap: 4 }}>{i > 0 && <span className="muted">then</span>}<kbd>{k}</kbd></span>)}</span>
            <span>{what}</span>
          </div>
        ))}
      </div>
    </Modal>
  );
}
