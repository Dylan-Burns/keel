import {describe, expect, it} from 'vitest';

import {applyTheme, isThemeChoice, resolveTheme} from './theme';

describe('theme', () => {
  it('resolves the system choice by the media query', () => {
    expect(resolveTheme('system', true)).toBe('dark');
    expect(resolveTheme('system', false)).toBe('light');
    expect(resolveTheme('light', true)).toBe('light');
    expect(resolveTheme('dark', false)).toBe('dark');
  });

  it('accepts only the 3 choices from storage', () => {
    expect(isThemeChoice('dark')).toBe(true);
    expect(isThemeChoice('blue')).toBe(false);
    expect(isThemeChoice(null)).toBe(false);
  });

  it('sets the data-theme attribute and the color scheme', () => {
    const root = document.createElement('html');
    applyTheme('dark', root);
    expect(root.dataset['theme']).toBe('dark');
    expect(root.style.colorScheme).toBe('dark');
  });
});
