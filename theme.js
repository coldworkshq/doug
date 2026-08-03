(function () {
  var KEY = 'doug-theme';
  var root = document.documentElement;
  try {
    if (localStorage.getItem(KEY) === 'dark') {
      root.setAttribute('data-theme', 'dark');
    }
  } catch (e) {}

  var MOON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z"/></svg>';
  var SUN = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>';

  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;

    function sync() {
      var dark = root.getAttribute('data-theme') === 'dark';
      btn.setAttribute('aria-pressed', dark ? 'true' : 'false');
      btn.setAttribute('title', dark ? 'Switch to light theme' : 'Switch to dark theme');
      btn.innerHTML = dark ? SUN : MOON;
    }

    btn.addEventListener('click', function () {
      var goingDark = root.getAttribute('data-theme') !== 'dark';
      if (goingDark) {
        root.setAttribute('data-theme', 'dark');
      } else {
        root.removeAttribute('data-theme');
      }
      try { localStorage.setItem(KEY, goingDark ? 'dark' : 'light'); } catch (e) {}
      sync();
    });

    sync();
  });
})();
