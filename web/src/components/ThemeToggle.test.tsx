import {act, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {THEME_KEY} from '../lib/theme';
import {ThemeToggle} from './ThemeToggle';

/** A fake dark-mode media query whose answer a test can flip. */
interface FakeQuery {
  matches: boolean;
  readonly listeners: Set<() => void>;
}

function fakeSystem(dark: boolean): FakeQuery {
  const query: FakeQuery = {matches: dark, listeners: new Set()};
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      get matches() {
        return query.matches;
      },
      addEventListener: (_: string, listener: () => void) =>
        query.listeners.add(listener),
      removeEventListener: (_: string, listener: () => void) =>
        query.listeners.delete(listener),
    })),
  );
  return query;
}

function theme(): string | undefined {
  return document.documentElement.dataset['theme'];
}

describe('ThemeToggle', () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset['theme'];
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('follows the system by default: dark system, dark page', () => {
    fakeSystem(true);
    render(<ThemeToggle />);
    expect(screen.getByTestId('theme-toggle')).toHaveAttribute(
      'data-choice',
      'system',
    );
    // No Auto option: the toggle marks the theme the system picked.
    expect(screen.queryByTestId('theme-system')).toBeNull();
    expect(screen.getByTestId('theme-dark')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(theme()).toBe('dark');
  });

  it('follows a change of the system setting before a choice', () => {
    const query = fakeSystem(false);
    render(<ThemeToggle />);
    expect(theme()).toBe('light');
    act(() => {
      query.matches = true;
      for (const listener of query.listeners) {
        listener();
      }
    });
    expect(theme()).toBe('dark');
  });

  it('persists an explicit choice and reads it back on the next load', () => {
    fakeSystem(false);
    const {unmount} = render(<ThemeToggle />);
    fireEvent.click(screen.getByRole('button', {name: 'Dark'}));
    expect(theme()).toBe('dark');
    expect(window.localStorage.getItem(THEME_KEY)).toBe('dark');
    unmount();
    render(<ThemeToggle />);
    expect(screen.getByTestId('theme-dark')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(theme()).toBe('dark');
    fireEvent.click(screen.getByRole('button', {name: 'Light'}));
    expect(window.localStorage.getItem(THEME_KEY)).toBe('light');
    expect(theme()).toBe('light');
    expect(screen.queryByRole('button', {name: 'Auto'})).toBeNull();
  });

  it('works when the storage throws', () => {
    fakeSystem(false);
    const get = vi
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => {
        throw new Error('blocked');
      });
    const set = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('blocked');
      });
    render(<ThemeToggle />);
    expect(theme()).toBe('light');
    fireEvent.click(screen.getByRole('button', {name: 'Dark'}));
    expect(theme()).toBe('dark');
    get.mockRestore();
    set.mockRestore();
  });
});
