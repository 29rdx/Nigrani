// Runs before the page paints, so the chosen look is there from the first frame (no flash of the default).
(function () {
  try {
    var ACCENTS = ['violet', 'emerald', 'ember', 'rose', 'mono'];
    var q = new URLSearchParams(location.search);
    var accent = q.get('accent') || localStorage.getItem('nigrani.accent') || 'ember';
    var theme = q.get('theme') || localStorage.getItem('nigrani.theme') || '';
    var root = document.documentElement;
    root.dataset.accent = ACCENTS.indexOf(accent) >= 0 ? accent : 'ember';
    if (theme === 'light' || theme === 'dark') root.dataset.theme = theme;
    var density = localStorage.getItem('nigrani.density');
    if (density === 'compact') root.dataset.density = 'compact';
  } catch (e) { /* storage blocked: the defaults apply */ }
})();
