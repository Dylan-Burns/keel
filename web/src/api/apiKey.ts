/**
 * The visitor's own Anthropic API key, kept in the browser only. A public
 * service (`/api/ready` reports `access: "public"`) answers a visitor with
 * this key: the page sends it in the `X-Anthropic-Api-Key` header of each
 * API call, and the server passes it on to Anthropic without storing it.
 * Session storage holds it by default; local storage only after the visitor
 * opts in with "Remember on this device". The key is never logged and never
 * put in a URL.
 */

/** The storage key of the Anthropic API key, in session or local storage. */
export const API_KEY_STORAGE_KEY = 'keel.anthropic_api_key';

/** The request header that carries the key (the server reads it). */
export const API_KEY_HEADER = 'X-Anthropic-Api-Key';

/** The shape the server accepts (`keel/api/auth.py`, `KEY_PATTERN`). */
export const API_KEY_PATTERN = /^sk-ant-[A-Za-z0-9_-]{16,250}$/;

/** Where to get a key. */
export const API_KEY_CONSOLE_URL = 'https://console.anthropic.com/';

/**
 * The error codes that ask the visitor for a key, or for a new one: the
 * question needs a key (HTTP 401), the key is malformed (HTTP 400), or
 * Anthropic refused it (the stream's `error` event).
 */
export const API_KEY_CODES: ReadonlySet<string> = new Set([
  'api_key_required',
  'invalid_api_key',
  'provider_auth_rejected',
]);

type Listener = () => void;

const keyListeners = new Set<Listener>();
const openListeners = new Set<Listener>();

function read(storage: () => Storage): string | null {
  try {
    return storage().getItem(API_KEY_STORAGE_KEY);
  } catch {
    return null;
  }
}

function write(storage: () => Storage, value: string | null): void {
  try {
    if (value === null) {
      storage().removeItem(API_KEY_STORAGE_KEY);
    } else {
      storage().setItem(API_KEY_STORAGE_KEY, value);
    }
  } catch {
    // Storage blocked: nothing to keep.
  }
}

const session = (): Storage => window.sessionStorage;
const local = (): Storage => window.localStorage;

function notify(): void {
  for (const listener of keyListeners) {
    listener();
  }
}

/**
 * Checks the shape of a key, as the server does.
 *
 * @param key The key, trimmed.
 * @return True when the server would accept the shape.
 */
export function isValidApiKey(key: string): boolean {
  return API_KEY_PATTERN.test(key);
}

/**
 * Reads the stored key: the tab's copy first, then the remembered one.
 *
 * @return The key, or null when none is stored or storage is blocked.
 */
export function getApiKey(): string | null {
  const key = read(session) ?? read(local);
  return key !== null && isValidApiKey(key) ? key : null;
}

/**
 * True when the stored key lives in local storage ("Remember on this
 * device").
 *
 * @return Whether the key is remembered.
 */
export function isApiKeyRemembered(): boolean {
  return read(session) === null && getApiKey() !== null;
}

/**
 * Stores a key in session storage, or in local storage on opt-in, and
 * removes it from the other one.
 *
 * @param key The key.
 * @param remember True to keep it on this device across sessions.
 * @return False when the key is malformed: nothing is stored.
 */
export function setApiKey(key: string, remember: boolean): boolean {
  const trimmed = key.trim();
  if (!isValidApiKey(trimmed)) {
    return false;
  }
  write(remember ? local : session, trimmed);
  write(remember ? session : local, null);
  notify();
  return true;
}

/** Removes the key from session and local storage. */
export function clearApiKey(): void {
  write(session, null);
  write(local, null);
  notify();
}

/**
 * Masks a key for display: the prefix and the last 4 characters.
 *
 * @param key The key.
 * @return The masked key, such as `sk-ant-...abcd`.
 */
export function maskApiKey(key: string): string {
  return `sk-ant-...${key.slice(-4)}`;
}

/**
 * Follows changes of the stored key.
 *
 * @param listener Called after each change.
 * @return The unsubscribe function.
 */
export function subscribeApiKey(listener: Listener): () => void {
  keyListeners.add(listener);
  return () => {
    keyListeners.delete(listener);
  };
}

/** Asks the API key settings of the page to open (an inline prompt does). */
export function openApiKeySettings(): void {
  for (const listener of openListeners) {
    listener();
  }
}

/**
 * Follows the requests to open the API key settings.
 *
 * @param listener Called on each request.
 * @return The unsubscribe function.
 */
export function onOpenApiKeySettings(listener: Listener): () => void {
  openListeners.add(listener);
  return () => {
    openListeners.delete(listener);
  };
}
