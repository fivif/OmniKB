/* OmniKB Theme controller — light / dark / system, persisted */
(function () {
  const STORAGE_KEY = 'omnikb-theme';
  const root = document.documentElement;

  function resolve(theme) {
    if (theme === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return theme;
  }

  function apply(theme) {
    const resolved = resolve(theme);
    if (theme === 'system') {
      root.removeAttribute('data-theme');
    } else {
      root.setAttribute('data-theme', resolved);
    }
    root.setAttribute('data-theme-pref', theme);
  }

  function get() {
    return localStorage.getItem(STORAGE_KEY) || 'system';
  }

  function set(theme) {
    if (!['light', 'dark', 'system'].includes(theme)) return;
    localStorage.setItem(STORAGE_KEY, theme);
    apply(theme);
    window.dispatchEvent(new CustomEvent('omni-theme-change', {
      detail: { theme, resolved: resolve(theme) }
    }));
  }

  function toggle() {
    const cur = resolve(get());
    set(cur === 'dark' ? 'light' : 'dark');
  }

  function cycle() {
    const order = ['light', 'dark', 'system'];
    const cur = get();
    set(order[(order.indexOf(cur) + 1) % order.length]);
  }

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (get() === 'system') apply('system');
  });

  apply(get());

  window.OmniTheme = { get, set, toggle, cycle, resolve };
})();
