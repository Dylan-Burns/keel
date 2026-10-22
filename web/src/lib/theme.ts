/**
 * The color theme of the page: dark, light, or the system setting (the
 * default). The choice lives in local storage under `keel.theme`; the
 * resolved theme is the `data-theme` attribute of the root element, which
 * the theme tokens of styles.css read. `public/theme-init.js` applies the
 * same choice before the first paint, because the Content-Security-Policy
 * blocks an inline script.
 */

/** The theme a user picks. */
export type ThemeChoice = 'system' | 'light' | 'dark';

/** The theme the page shows. */
export type Theme = 'light' | 'dark';

/** The local storage key of the choice (public/theme-init.js reads it too). */
export const THEME_KEY = 'keel.theme';

/** The media query of a dark system setting. */
export const DARK_QUERY = '(prefers-color-scheme: dark)';

/** The choices in the order of the toggle. */
export const THEME_CHOICES: readonly ThemeChoice[] = [
  'system',
  'light',
  'dark',
];

/**
 * True when a value is a theme choice.
 *
 * @param value Any stored value.
 * @return Whether it names a choice.
 */
export function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === 'system' || value === 'light' || value === 'dark';
}

/**
 * Reads the stored choice. Storage can be absent or blocked (a private
 * window, a sandboxed frame): the page then follows the system.
 *
 * @return The stored choice, else `system`.
 */
export function readThemeChoice(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return isThemeChoice(value) ? value : 'system';
  } catch {
    return 'system';
  }
}

/**
 * Stores the choice; `system` removes the key. A blocked storage keeps the
 * choice for this page view only.
 *
 * @param choice The choice.
 */
export function saveThemeChoice(choice: ThemeChoice): void {
  try {
    if (choice === 'system') {
      window.localStorage.removeItem(THEME_KEY);
    } else {
      window.localStorage.setItem(THEME_KEY, choice);
    }
  } catch {
    // Storage is blocked: the choice holds until the page reloads.
  }
}

/**
 * True when the system asks for a dark page.
 *
 * @return Whether the dark media query matches.
 */
export function systemPrefersDark(): boolean {
  return (
    typeof window.matchMedia === 'function' &&
    window.matchMedia(DARK_QUERY).matches
  );
}

/**
 * Resolves a choice to the theme the page shows.
 *
 * @param choice The choice.
 * @param prefersDark True when the system setting is dark.
 * @return The theme.
 */
export function resolveTheme(choice: ThemeChoice, prefersDark: boolean): Theme {
  if (choice === 'system') {
    return prefersDark ? 'dark' : 'light';
  }
  return choice;
}

/**
 * Sets the resolved theme on the root element: the `data-theme` attribute
 * for the tokens and `color-scheme` for the native controls.
 *
 * @param theme The theme.
 * @param root The root element.
 */
export function applyTheme(
  theme: Theme,
  root: HTMLElement = document.documentElement,
): void {
  root.dataset['theme'] = theme;
  root.style.colorScheme = theme;
}
