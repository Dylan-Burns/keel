import type {JSX} from 'react';
import {useEffect, useState} from 'react';

import type {ThemeChoice} from '../lib/theme';
import {
  DARK_QUERY,
  THEME_CHOICES,
  applyTheme,
  readThemeChoice,
  resolveTheme,
  saveThemeChoice,
  systemPrefersDark,
} from '../lib/theme';

const LABELS: Readonly<Record<ThemeChoice, string>> = {
  system: 'Auto',
  light: 'Light',
  dark: 'Dark',
};

const TITLES: Readonly<Record<ThemeChoice, string>> = {
  system: 'Follow the system theme',
  light: 'Light theme',
  dark: 'Dark theme',
};

/**
 * The theme toggle of the top bar: Auto (the system setting, the default),
 * Light, or Dark. The choice persists in local storage; with Auto the page
 * follows a change of the system setting at once.
 *
 * @return The toggle.
 */
export function ThemeToggle(): JSX.Element {
  const [choice, setChoice] = useState<ThemeChoice>(readThemeChoice);
  useEffect(() => {
    applyTheme(resolveTheme(choice, systemPrefersDark()));
    if (choice !== 'system' || typeof window.matchMedia !== 'function') {
      return;
    }
    const query = window.matchMedia(DARK_QUERY);
    const follow = (): void =>
      applyTheme(resolveTheme('system', query.matches));
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
      {THEME_CHOICES.map(option => (
        <button
          key={option}
          type="button"
          className="segmented-option"
          aria-pressed={choice === option}
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
