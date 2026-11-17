import {afterEach, describe, expect, it, vi} from 'vitest';

import {
  API_KEY_STORAGE_KEY,
  clearApiKey,
  getApiKey,
  isApiKeyRemembered,
  isValidApiKey,
  maskApiKey,
  onOpenApiKeySettings,
  openApiKeySettings,
  setApiKey,
  subscribeApiKey,
} from './apiKey';

const KEY = 'sk-ant-api03-abcdefghijklmnop_QRST-wxyz';

afterEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
});

describe('apiKey', () => {
  it('checks the shape the server checks', () => {
    expect(isValidApiKey(KEY)).toBe(true);
    expect(isValidApiKey('sk-ant-short')).toBe(false);
    expect(isValidApiKey('sk-proj-abcdefghijklmnopqrstuvwxyz')).toBe(false);
    expect(isValidApiKey(`${KEY} `)).toBe(false);
    expect(isValidApiKey(`sk-ant-${'a'.repeat(251)}`)).toBe(false);
  });

  it('keeps the key in session storage by default', () => {
    expect(setApiKey(` ${KEY} `, false)).toBe(true);
    expect(window.sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBe(KEY);
    expect(window.localStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
    expect(getApiKey()).toBe(KEY);
    expect(isApiKeyRemembered()).toBe(false);
  });

  it('keeps the key in local storage only on opt-in', () => {
    setApiKey(KEY, false);
    setApiKey(KEY, true);
    expect(window.localStorage.getItem(API_KEY_STORAGE_KEY)).toBe(KEY);
    expect(window.sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
    expect(getApiKey()).toBe(KEY);
    expect(isApiKeyRemembered()).toBe(true);
  });

  it('stores nothing for a malformed key', () => {
    expect(setApiKey('not-a-key', false)).toBe(false);
    expect(getApiKey()).toBeNull();
  });

  it('ignores a malformed stored value', () => {
    window.sessionStorage.setItem(API_KEY_STORAGE_KEY, 'junk');
    expect(getApiKey()).toBeNull();
  });

  it('removes the key from both stores and tells the listeners', () => {
    const listener = vi.fn();
    const stop = subscribeApiKey(listener);
    setApiKey(KEY, true);
    window.sessionStorage.setItem(API_KEY_STORAGE_KEY, KEY);
    clearApiKey();
    expect(window.sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
    expect(window.localStorage.getItem(API_KEY_STORAGE_KEY)).toBeNull();
    expect(listener).toHaveBeenCalledTimes(2);
    stop();
    setApiKey(KEY, false);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it('masks all but the prefix and the last 4 characters', () => {
    expect(maskApiKey(KEY)).toBe('sk-ant-...wxyz');
  });

  it('passes the open requests to the settings', () => {
    const listener = vi.fn();
    const stop = onOpenApiKeySettings(listener);
    openApiKeySettings();
    expect(listener).toHaveBeenCalledOnce();
    stop();
    openApiKeySettings();
    expect(listener).toHaveBeenCalledOnce();
  });
});
