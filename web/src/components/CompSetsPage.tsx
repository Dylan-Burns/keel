import type {JSX} from 'react';
import {useEffect, useState} from 'react';

import {
  ApiError,
  deleteCompSet,
  fetchCompSets,
  getToken,
  saveCompSet,
  setToken,
} from '../api/client';
import type {CompSetItem} from '../api/types';
import {TokenField} from './TokenField';

/** The load state of the page. */
type Load =
  | {readonly kind: 'loading'}
  | {readonly kind: 'no_token'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly items: readonly CompSetItem[]};

/**
 * Splits the tickers field at commas and white space.
 *
 * @param text The field as typed.
 * @return The upper-case tickers.
 */
function tickersOf(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .filter(Boolean)
    .map(t => t.toUpperCase());
}

/**
 * The message of a failed save or delete.
 *
 * @param error The error.
 * @return The text for the page.
 */
function messageOf(error: unknown): string {
  if (error instanceof ApiError && error.status === 403) {
    return 'Only the owner of this comp set or an admin can change it.';
  }
  if (error instanceof ApiError && error.status === 400) {
    return error.message;
  }
  return 'The comp set could not be saved.';
}

/**
 * The comp sets page at `/compsets` (chapter 27.2): the saved comp sets of
 * the firm, a form to create or replace 1 (a name and its tickers), and a
 * delete button on the sets the user may change. A question names a set
 * as `my <name> comps`; the status line lists the tickers outside the
 * index, which `keel add` adds (chapter 26).
 *
 * @return The page.
 */
export function CompSetsPage(): JSX.Element {
  const [version, setVersion] = useState(0);
  const [name, setName] = useState('');
  const [tickers, setTickers] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [load, setLoad] = useState<Load>(() =>
    getToken() === null ? {kind: 'no_token'} : {kind: 'loading'},
  );
  useEffect(() => {
    if (getToken() === null) {
      return;
    }
    let cancelled = false;
    fetchCompSets()
      .then(list => {
        if (!cancelled) {
          setLoad({kind: 'ready', items: list.items});
        }
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          setLoad({kind: 'no_token'});
        } else {
          setLoad({kind: 'error', message: 'The comp sets could not load.'});
        }
      });
    return () => {
      cancelled = true;
    };
  }, [version]);
  const onSave = (token: string): void => {
    setToken(token);
    setLoad({kind: 'loading'});
    setVersion(n => n + 1);
  };
  const onSubmit = (): void => {
    const list = tickersOf(tickers);
    if (name.trim() === '' || list.length === 0) {
      setNotice('Give a name and at least 1 ticker.');
      return;
    }
    saveCompSet(name.trim(), list)
      .then(saved => {
        const missing =
          saved.missing.length > 0
            ? ` Not in the index yet: ${saved.missing.join(', ')} (keel add).`
            : '';
        setNotice(`Saved. Ask about "my ${saved.name} comps".${missing}`);
        setName('');
        setTickers('');
        setVersion(n => n + 1);
      })
      .catch((error: unknown) => setNotice(messageOf(error)));
  };
  const onDelete = (item: CompSetItem): void => {
    deleteCompSet(item.name)
      .then(() => {
        setNotice(`Deleted ${item.name}.`);
        setVersion(n => n + 1);
      })
      .catch((error: unknown) => setNotice(messageOf(error)));
  };
  return (
    <div
      className="min-h-screen bg-paper font-sans text-ink"
      data-testid="compsets-page"
      data-load={load.kind}
    >
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
        <h1 className="text-lg font-semibold">Comp sets</h1>
        <button
          type="button"
          className="text-sm text-accent underline"
          onClick={() => window.location.assign('/')}
        >
          Back to questions
        </button>
        <div className="ml-auto">
          <TokenField
            hasToken={load.kind !== 'no_token'}
            rejected={load.kind === 'no_token' && getToken() !== null}
            onSave={onSave}
          />
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl space-y-4 px-4 py-6">
        {load.kind === 'no_token' && (
          <p className="text-sm text-slate-600">
            Enter your access token to read the comp sets.
          </p>
        )}
        {load.kind === 'loading' && (
          <p className="text-sm text-slate-600">Loading the comp sets.</p>
        )}
        {load.kind === 'error' && (
          <p className="text-sm text-red-700" role="alert">
            {load.message}
          </p>
        )}
        {load.kind === 'ready' && (
          <>
            <form
              className="flex flex-wrap items-end gap-2 rounded border border-slate-200 bg-white p-3 text-sm"
              data-testid="compset-form"
              onSubmit={event => {
                event.preventDefault();
                onSubmit();
              }}
            >
              <label className="flex flex-col gap-1">
                <span className="text-xs text-slate-500">Name</span>
                <input
                  className="w-48 rounded border border-slate-300 px-2 py-1"
                  value={name}
                  placeholder="software"
                  maxLength={40}
                  data-testid="compset-name"
                  onChange={event => setName(event.target.value)}
                />
              </label>
              <label className="flex flex-1 flex-col gap-1">
                <span className="text-xs text-slate-500">Tickers</span>
                <input
                  className="min-w-0 rounded border border-slate-300 px-2 py-1"
                  value={tickers}
                  placeholder="MSFT, ORCL, CRM, ADBE"
                  data-testid="compset-tickers"
                  onChange={event => setTickers(event.target.value)}
                />
              </label>
              <button
                type="submit"
                className="rounded bg-accent px-3 py-1 text-white"
                data-testid="compset-save"
              >
                Save
              </button>
            </form>
            {notice !== null && (
              <p
                className="text-sm text-slate-700"
                role="status"
                data-testid="compset-notice"
              >
                {notice}
              </p>
            )}
            {load.items.length === 0 ? (
              <p className="text-sm text-slate-600" data-testid="compset-empty">
                No comp sets yet. Save one, then ask about &quot;my NAME
                comps&quot;.
              </p>
            ) : (
              <ul className="space-y-3" aria-label="Comp sets">
                {load.items.map(item => (
                  <li
                    key={item.name}
                    className="flex flex-wrap items-center gap-3 rounded border border-slate-200 bg-white p-3 text-sm"
                    data-testid="compset-item"
                    data-name={item.name}
                  >
                    <span className="font-medium">my {item.name} comps</span>
                    <span className="font-mono text-xs">
                      {item.tickers.join(' ')}
                    </span>
                    {item.missing.length > 0 && (
                      <span
                        className="text-xs text-amber-700"
                        data-testid="compset-missing"
                      >
                        not in the index: {item.missing.join(', ')}
                      </span>
                    )}
                    <span className="text-xs text-slate-500">
                      {item.owner ?? 'admin'}
                    </span>
                    {item.editable && (
                      <span className="ml-auto flex gap-2">
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-2 py-1"
                          data-testid="compset-edit"
                          onClick={() => {
                            setName(item.name);
                            setTickers(item.tickers.join(', '));
                          }}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-2 py-1"
                          data-testid="compset-delete"
                          onClick={() => onDelete(item)}
                        >
                          Delete
                        </button>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </main>
    </div>
  );
}
