// Appearance: the mode (light / dark / follow the system), the accent colour and the spacing (tested in appearance.test.js).

export const ACCENTS = [
  { id: 'ember', label: 'Ember', swatch: '#f97316', logo: ['#f5873a', '#bf4b0b'] },
  { id: 'violet', label: 'Violet', swatch: '#7455f0', logo: ['#8f72ff', '#6540e8'] },
  { id: 'emerald', label: 'Emerald', swatch: '#10b981', logo: ['#18b886', '#0a7a57'] },
  { id: 'rose', label: 'Rose', swatch: '#f43f5e', logo: ['#f0577d', '#cc1f4d'] },
  { id: 'mono', label: 'Mono', swatch: '#b9b9c2', logo: ['#4b4b52', '#161618'] },
];
export const DEFAULT_ACCENT = 'ember';
export const MODES = [['', 'System'], ['light', 'Light'], ['dark', 'Dark']];

export const isAccent = (id) => ACCENTS.some((a) => a.id === id);
export const cleanAccent = (id) => (isAccent(id) ? id : DEFAULT_ACCENT);
export const cleanMode = (m) => (m === 'light' || m === 'dark' ? m : '');
export const accentOf = (id) => ACCENTS.find((a) => a.id === id) || ACCENTS[0];

/** What "System" means right now. */
export function resolveMode(mode, systemIsDark) {
  const m = cleanMode(mode);
  return m || (systemIsDark ? 'dark' : 'light');
}

/** The URL may carry ?accent=ember&theme=dark to look at (or share) a look without saving it. */
export function fromQuery(search) {
  const q = new URLSearchParams(search || '');
  return { accent: isAccent(q.get('accent')) ? q.get('accent') : null, mode: ['light', 'dark'].includes(q.get('theme')) ? q.get('theme') : null };
}
