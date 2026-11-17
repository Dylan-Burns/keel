import {act, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {
  API_KEY_STORAGE_KEY,
  getApiKey,
  openApiKeySettings,
  setApiKey,
} from '../api/apiKey';
import {TOKEN_KEY} from '../api/client';
import {ApiKeySettings} from './ApiKeySettings';

const KEY = 'sk-ant-api03-abcdefghijklmnop_QRST-wxyz';

afterEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
});

function openPanel(): void {
  fireEvent.click(screen.getByTestId('api-key-button'));
}

function typeKey(value: string): void {
  fireEvent.change(screen.getByTestId('api-key-input'), {target: {value}});
}

describe('ApiKeySettings', () => {
  it('reminds the visitor to remove and deactivate the key', () => {
    render(<ApiKeySettings />);
    openPanel();
    const note = screen.getByTestId('api-key-cleanup');
    expect(note).toHaveClass('notice-down');
    expect(note).toHaveTextContent('When you are done');
    expect(note).toHaveTextContent('delete or deactivate it');
    expect(
      screen.getByRole('link', {name: 'Anthropic Console'}),
    ).toHaveAttribute('href', 'https://console.anthropic.com/');
  });

  it('explains where the key goes and where to get one', () => {
    render(<ApiKeySettings />);
    expect(screen.getByTestId('api-key-button')).toHaveTextContent(
      'Add API key',
    );
    openPanel();
    const panel = screen.getByRole('dialog', {name: 'Anthropic API key'});
    expect(panel).toHaveTextContent('only to this server');
    expect(panel).toHaveTextContent('does not store it');
    expect(
      screen.getByRole('link', {name: 'console.anthropic.com'}),
    ).toHaveAttribute('href', 'https://console.anthropic.com/');
  });

  it('refuses a malformed key and stores nothing', () => {
    render(<ApiKeySettings />);
    openPanel();
    typeKey('sk-proj-1234567890abcdefghij');
    fireEvent.click(screen.getByRole('button', {name: 'Save key'}));
    expect(screen.getByRole('alert')).toHaveTextContent('sk-ant-');
    expect(getApiKey()).toBeNull();
  });

  it('saves the key for this tab and shows it masked', () => {
    render(<ApiKeySettings />);
    openPanel();
    typeKey(KEY);
    fireEvent.click(screen.getByRole('button', {name: 'Save key'}));
    expect(window.sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBe(KEY);
    expect(window.localStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
    expect(screen.getByTestId('api-key-stored')).toHaveTextContent(
      'sk-ant-...wxyz',
    );
    expect(screen.getByTestId('api-key-stored')).toHaveTextContent(
      'This tab only',
    );
    expect(screen.getByTestId('api-key-button')).toHaveTextContent(
      'API key sk-ant-...wxyz',
    );
    // The full key is never on the page.
    expect(document.body.textContent).not.toContain(KEY);
    expect(screen.getByTestId('api-key-input')).toHaveValue('');
  });

  it('remembers the key on this device only on opt-in', () => {
    render(<ApiKeySettings />);
    openPanel();
    typeKey(KEY);
    fireEvent.click(screen.getByLabelText('Remember on this device'));
    fireEvent.click(screen.getByRole('button', {name: 'Save key'}));
    expect(window.localStorage.getItem(API_KEY_STORAGE_KEY)).toBe(KEY);
    expect(window.sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
    expect(screen.getByTestId('api-key-stored')).toHaveTextContent(
      'Remembered on this device',
    );
  });

  it('removes the key from both stores', () => {
    setApiKey(KEY, true);
    window.sessionStorage.setItem(API_KEY_STORAGE_KEY, KEY);
    render(<ApiKeySettings />);
    openPanel();
    fireEvent.click(screen.getByTestId('api-key-remove'));
    expect(window.localStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
    expect(screen.queryByTestId('api-key-stored')).toBeNull();
    expect(screen.getByTestId('api-key-button')).toHaveTextContent(
      'Add API key',
    );
  });

  it('opens on a request of an inline prompt and closes on Escape', () => {
    render(<ApiKeySettings />);
    expect(screen.queryByTestId('api-key-settings')).toBeNull();
    act(() => openApiKeySettings());
    expect(screen.getByTestId('api-key-settings')).toBeInTheDocument();
    expect(screen.getByTestId('api-key-input')).toHaveFocus();
    fireEvent.keyDown(document, {key: 'Escape'});
    expect(screen.queryByTestId('api-key-settings')).toBeNull();
  });

  it('signs an admin in with a Keel access token', () => {
    const onTokenChange = vi.fn();
    render(<ApiKeySettings onTokenChange={onTokenChange} />);
    openPanel();
    fireEvent.click(screen.getByTestId('admin-sign-in'));
    fireEvent.change(screen.getByTestId('admin-token'), {
      target: {value: 'admin-token'},
    });
    fireEvent.click(screen.getByRole('button', {name: 'Sign in'}));
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBe('admin-token');
    expect(onTokenChange).toHaveBeenCalledOnce();
  });

  it('signs a signed-in user out', () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'admin-token');
    const onTokenChange = vi.fn();
    render(<ApiKeySettings onTokenChange={onTokenChange} />);
    openPanel();
    expect(screen.getByTestId('api-key-settings')).toHaveTextContent(
      'service key',
    );
    fireEvent.click(screen.getByTestId('admin-sign-out'));
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(onTokenChange).toHaveBeenCalledOnce();
  });
});
