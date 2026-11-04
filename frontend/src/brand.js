// The browser tab: a title and a favicon that say how many alerts are firing (tested in brand.test.js).
import { accentOf } from './appearance.js';

/** "(2) Alerts · Nigrani": the count first, so it shows even in a narrow tab. */
export function pageTitle(count, title, app) {
  return `${count > 0 ? `(${count > 99 ? '99+' : count}) ` : ''}${title} · ${app}`;
}

/** The logo in the chosen accent as an SVG data URL, with a red dot in the corner while something is firing. */
export function faviconHref(count, accent = 'ember') {
  const [a, b] = accentOf(accent).logo;
  const dot = count > 0 ? "<circle cx='25' cy='7' r='7' fill='#e5484d' stroke='white' stroke-width='1.6'/>" : '';
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='${a}'/><stop offset='1' stop-color='${b}'/></linearGradient></defs><rect width='32' height='32' rx='8' fill='url(#g)'/><path d='M5 16.5h5.2l2.6-6.4 4.4 11.6 2.8-5.2H27' fill='none' stroke='white' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/>${dot}</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}
