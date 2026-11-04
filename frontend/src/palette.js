// Fuzzy matching for the command palette (pure functions, tested in palette.test.js).

/** Score `text` against `query`: higher is better, -1 means no match. Exact > prefix > word start > subsequence. */
export function score(query, text) {
  const q = String(query || '').trim().toLowerCase();
  const t = String(text || '').toLowerCase();
  if (!q) return 0;
  if (t === q) return 1000;
  if (t.startsWith(q)) return 800 - t.length;
  const at = t.indexOf(q);
  if (at >= 0) return (t[at - 1] === ' ' || t[at - 1] === '-' || t[at - 1] === '/' ? 600 : 500) - at;
  // every character of the query, in order (e.g. "ctr" finds "containers")
  let i = 0; let gaps = 0; let last = -1;
  for (let k = 0; k < t.length && i < q.length; k += 1) {
    if (t[k] === q[i]) { if (last >= 0 && k - last > 1) gaps += k - last; last = k; i += 1; }
  }
  return i === q.length ? Math.max(1, 300 - gaps - t.length) : -1;
}

/** items: [{label, hint?, group, ...}] -> best matches first, at most `limit`, keeping each group's order for an empty query. */
export function rank(items, query, limit = 40) {
  const q = String(query || '').trim();
  if (!q) return items.slice(0, limit);
  return items
    .map((it, n) => ({ it, n, s: Math.max(score(q, it.label), score(q, it.hint || '') - 150) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || a.n - b.n)
    .slice(0, limit)
    .map((x) => x.it);
}

/** "g" then a letter, within a second, jumps to a page. Returns the route for a pressed pair, or null. */
export const GOTO = { o: '/overview', a: '/alerts/active', c: '/containers', h: '/host', u: '/uptime', i: '/integrations', d: '/deploys', s: '/slos', l: '/logs' };
export function gotoRoute(letter) { return GOTO[String(letter || '').toLowerCase()] || null; }

/** Keystrokes typed into a field must never trigger a shortcut. */
export function isTyping(target) {
  if (!target || !target.tagName) return false;
  const tag = target.tagName.toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable === true;
}
