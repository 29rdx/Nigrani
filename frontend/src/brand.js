// The browser tab: a title and a favicon that say how many alerts are firing (tested in brand.test.js).

/** "(2) Alerts · Nigrani": the count first, so it shows even in a narrow tab. */
export function pageTitle(count, title, app) {
  return `${count > 0 ? `(${count > 99 ? '99+' : count}) ` : ''}${title} · ${app}`;
}

/** The logo as an SVG data URL, with a red dot in the corner while something is firing. */
export function faviconHref(count) {
  const dot = count > 0 ? "<circle cx='25' cy='7' r='7' fill='%23e5484d' stroke='white' stroke-width='1.6'/>" : '';
  return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0' stop-color='%236b93ff'/%3E%3Cstop offset='1' stop-color='%232f5fe3'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='32' height='32' rx='8' fill='url(%23g)'/%3E%3Cpath d='M5 16.5h5.2l2.6-6.4 4.4 11.6 2.8-5.2H27' fill='none' stroke='white' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E${encodeURIComponent(dot)}%3C/svg%3E`;
}
