/* global window, document */
// Applies the stored color theme before the first paint (src/lib/theme.ts
// holds the same rules). An external file, because the Content-Security-
// Policy of the API blocks inline scripts.
(function () {
  let choice = 'system';
  try {
    const stored = window.localStorage.getItem('keel.theme');
    if (stored === 'light' || stored === 'dark') {
      choice = stored;
    }
  } catch {
    choice = 'system';
  }
  const dark =
    choice === 'dark' ||
    (choice === 'system' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches);
  const theme = dark ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;
})();
