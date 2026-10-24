import type {JSX} from 'react';
import {useEffect, useState} from 'react';

import type {Theme, ThemeChoice} from '../lib/theme';
import {
  DARK_QUERY,
  applyTheme,
  readThemeChoice,
  resolveTheme,
  saveThemeChoice,
  systemPrefersDark,
} from '../lib/theme';

/** The themes the toggle offers; the system theme is only the default. */
const OPTIONS: readonly Theme[] = ['light', 'dark'];

const LABELS: Readonly<Record<Theme, string>> = {
  light: 'Light',
  dark: 'Dark',
};

const TITLES: Readonly<Record<Theme, string>> = {
  light: 'Light theme',
  dark: 'Dark theme',
};

/**
 * The theme toggle of the top bar: Light or Dark. Before a choice the page
 * follows the system setting, and the toggle marks the theme it shows. The
 * choice persists in local storage.
 *
 * @return The toggle.
 */
export function ThemeToggle(): JSX.Element {
  const [choice, setChoice] = useState<ThemeChoice>(readThemeChoice);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);
  const shown = resolveTheme(choice, systemDark);
  useEffect(() => {
    applyTheme(shown);
  }, [shown]);
  useEffect(() => {
    if (choice !== 'system' || typeof window.matchMedia !== 'function') {
      return;
    }
    const query = window.matchMedia(DARK_QUERY);
    const follow = (): void => setSystemDark(query.matches);
    query.addEventListener('change', follow);
    return () => query.removeEventListener('change', follow);
  }, [choice]);
  const pick = (next: ThemeChoice): void => {
    saveThemeChoice(next);
    setChoice(next);
  };
  return (
    <div
      className="segmented"
      role="group"
      aria-label="Color theme"
      data-testid="theme-toggle"
      data-choice={choice}
    >
      {OPTIONS.map(option => (
        <button
          key={option}
          type="button"
          className="segmented-option"
          aria-pressed={shown === option}
          title={TITLES[option]}
          data-testid={`theme-${option}`}
          onClick={() => pick(option)}
        >
          {LABELS[option]}
        </button>
      ))}
    </div>
  );
}
