import type {FormEvent, JSX} from 'react';
import {useEffect, useId, useRef, useState, useSyncExternalStore} from 'react';

import {
  API_KEY_CONSOLE_URL,
  clearApiKey,
  getApiKey,
  isApiKeyRemembered,
  isValidApiKey,
  maskApiKey,
  onOpenApiKeySettings,
  setApiKey,
  subscribeApiKey,
} from '../api/apiKey';
import {getToken} from '../api/client';
import {AdminSignIn} from './AdminSignIn';

/** Props of ApiKeySettings. */
export interface ApiKeySettingsProps {
  /** Runs after the admin token changes; the default reloads the page. */
  readonly onTokenChange?: () => void;
}

/**
 * The API key settings of a public service, behind a button in the top
 * bar: the visitor pastes their own Anthropic API key, which the browser
 * keeps (this tab only, or this device on opt-in) and sends to this server
 * with each question. The panel shows the stored key masked, removes it,
 * and holds the quiet admin sign in. An inline prompt of the page can open
 * it (`openApiKeySettings`).
 *
 * @param props The token change handler.
 * @return The button and its panel.
 */
export function ApiKeySettings({
  onTokenChange,
}: ApiKeySettingsProps): JSX.Element {
  const key = useSyncExternalStore(subscribeApiKey, getApiKey);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const panelId = useId();
  const inputId = useId();
  const rememberId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(
    () =>
      onOpenApiKeySettings(() => {
        setSaved(false);
        setOpen(true);
      }),
    [],
  );
  useEffect(() => {
    if (!open) {
      return;
    }
    inputRef.current?.focus();
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };
    const onPointer = (event: MouseEvent): void => {
      const root = rootRef.current;
      if (root !== null && !root.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onPointer);
    };
  }, [open]);

  const submit = (event: FormEvent): void => {
    event.preventDefault();
    const value = draft.trim();
    if (!isValidApiKey(value)) {
      setError(
        'That is not an Anthropic API key. A key starts with sk-ant- and ' +
          'holds only letters, digits, - and _.',
      );
      return;
    }
    setApiKey(value, remember);
    setDraft('');
    setError(null);
    setSaved(true);
  };
  const remove = (): void => {
    clearApiKey();
    setSaved(false);
  };
  const signedIn = getToken() !== null;
  const label = signedIn
    ? 'Settings'
    : key === null
      ? 'Add API key'
      : `API key ${maskApiKey(key)}`;

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        className={`btn ${key === null && !signedIn ? 'btn-primary' : ''}`}
        aria-expanded={open}
        aria-controls={panelId}
        data-testid="api-key-button"
        onClick={() => {
          setSaved(false);
          setOpen(value => !value);
        }}
      >
        {label}
      </button>
      {open && (
        <section
          id={panelId}
          role="dialog"
          aria-label="Anthropic API key"
          className="panel absolute right-0 top-full z-40 mt-1.5 w-[min(24rem,calc(100vw-1.5rem))] space-y-3 p-3 text-left shadow-lg"
          data-testid="api-key-settings"
        >
          <div className="space-y-1">
            <h2 className="font-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-ink">
              Your Anthropic API key
            </h2>
            <p className="text-[12px] text-ink-2">
              Your browser sends the key only to this server with each question,
              and the server passes it on to Anthropic. The server does not
              store it.
            </p>
            <p className="text-[12px] text-ink-2">
              Get a key at{' '}
              <a
                href={API_KEY_CONSOLE_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent underline underline-offset-2"
              >
                console.anthropic.com
              </a>
              . The example questions answer without one.
            </p>
            {signedIn && (
              <p className="text-[12px] text-ink-2">
                You are signed in, so your questions use the service key.
              </p>
            )}
          </div>
          <p
            className="notice notice-down text-[12px] text-ink"
            data-testid="api-key-cleanup"
          >
            <strong className="font-semibold">When you are done,</strong> remove
            the key here, then delete or deactivate it in the{' '}
            <a
              href={API_KEY_CONSOLE_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2"
            >
              Anthropic Console
            </a>
            . Removing it here only clears this browser.
          </p>
          {key !== null && (
            <div
              className="flex flex-wrap items-center gap-2"
              data-testid="api-key-stored"
            >
              <span className="num text-[12px] text-ink">
                {maskApiKey(key)}
              </span>
              <span className="text-[11px] text-muted">
                {isApiKeyRemembered()
                  ? 'Remembered on this device'
                  : 'This tab only'}
              </span>
              <button
                type="button"
                className="btn btn-danger ml-auto"
                data-testid="api-key-remove"
                onClick={remove}
              >
                Remove key
              </button>
            </div>
          )}
          <form className="space-y-2" onSubmit={submit} noValidate>
            <label
              className="block font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted"
              htmlFor={inputId}
            >
              {key === null ? 'API key' : 'Replace the key'}
            </label>
            <input
              id={inputId}
              ref={inputRef}
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="sk-ant-..."
              className="input w-full"
              value={draft}
              aria-invalid={error !== null}
              onChange={event => {
                setDraft(event.target.value);
                setError(null);
              }}
              data-testid="api-key-input"
            />
            <div className="flex flex-wrap items-center gap-2">
              <input
                id={rememberId}
                type="checkbox"
                checked={remember}
                onChange={event => setRemember(event.target.checked)}
                data-testid="api-key-remember"
              />
              <label className="text-[12px] text-ink-2" htmlFor={rememberId}>
                Remember on this device
              </label>
              <button type="submit" className="btn btn-primary ml-auto">
                Save key
              </button>
            </div>
            {error !== null && (
              <p className="text-[12px] text-down" role="alert">
                {error}
              </p>
            )}
            {saved && error === null && (
              <p className="text-[12px] text-up" role="status">
                Saved. Your next question uses this key.
              </p>
            )}
          </form>
          <div className="border-t border-line pt-2">
            <AdminSignIn
              {...(onTokenChange === undefined
                ? {}
                : {onChange: onTokenChange})}
            />
          </div>
        </section>
      )}
    </div>
  );
}
