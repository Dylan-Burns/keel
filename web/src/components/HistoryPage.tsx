import type {JSX} from 'react';
import {useEffect, useState, useSyncExternalStore} from 'react';

import {canCallApi} from '../api/access';
import {getApiKey, openApiKeySettings, subscribeApiKey} from '../api/apiKey';
import {
  ApiError,
  RERUN_QUESTION_KEY,
  fetchHistory,
  getToken,
  setToken,
  writeSession,
} from '../api/client';
import type {HistoryResponse, HistoryScope} from '../api/types';
import {copyText, sharePath, shareUrl} from '../lib/links';
import {PageBar} from './PageBar';
import {CredentialField} from './CredentialField';

/** The load state of the page. */
type Load =
  | {readonly kind: 'loading'}
  | {readonly kind: 'no_token'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly data: HistoryResponse};

/**
 * Formats an ISO timestamp for the list, in the browser's time zone.
 *
 * @param timestamp The ISO 8601 time.
 * @return The local date and time, or the raw text when it does not parse.
 */
function when(timestamp: string): string {
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? timestamp : parsed.toLocaleString();
}

/** The user name the server gives every visitor without an API key. */
const KEYLESS_VISITOR = 'visitor';

/**
 * The line over the list: whose questions it shows.
 *
 * @param data The history.
 * @param scope The scope of the list.
 * @return The line.
 */
function ownerLine(data: HistoryResponse, scope: HistoryScope): string {
  if (scope === 'all') {
    return 'Questions of every user';
  }
  if (data.role === 'visitor') {
    return data.user === KEYLESS_VISITOR
      ? 'No API key: no history kept'
      : 'Questions asked with your API key';
  }
  return `Questions of ${data.user}`;
}

/**
 * The history page at `/history`: the questions of the
 * signed-in user, newest first, from the audit log. A visitor of a public
 * service sees the questions of their own API key; the server keeps no
 * history for a visitor without one. Each row opens the
 * stored answer at its shareable link, copies the link, or puts the
 * question back in the question box (Re-run), where the user presses Ask.
 * An admin can switch to every user's questions.
 *
 * @return The page.
 */
export function HistoryPage(): JSX.Element {
  const [tokenCount, setTokenCount] = useState(0);
  const [scope, setScope] = useState<HistoryScope>('own');
  const [copied, setCopied] = useState<string | null>(null);
  // A visitor's history follows their key: the server names them by it.
  const apiKey = useSyncExternalStore(subscribeApiKey, getApiKey);
  const [load, setLoad] = useState<Load>(() =>
    canCallApi() ? {kind: 'loading'} : {kind: 'no_token'},
  );
  useEffect(() => {
    if (!canCallApi()) {
      return;
    }
    let cancelled = false;
    fetchHistory(scope)
      .then(data => {
        if (!cancelled) {
          setLoad({kind: 'ready', data});
        }
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          setLoad({kind: 'no_token'});
        } else {
          setLoad({kind: 'error', message: 'The history could not load.'});
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tokenCount, scope, apiKey]);
  const onSave = (token: string): void => {
    setToken(token);
    setLoad({kind: 'loading'});
    setTokenCount(n => n + 1);
  };
  const onScope = (next: HistoryScope): void => {
    setLoad({kind: 'loading'});
    setScope(next);
  };
  const onCopy = (requestId: string): void => {
    copyText(shareUrl(requestId))
      .then(() => setCopied(requestId))
      .catch(() => setCopied(null));
  };
  const isAdmin = load.kind === 'ready' && load.data.role === 'admin';
  return (
    <div
      className="min-h-screen bg-canvas font-sans text-ink"
      data-testid="history-page"
      data-load={load.kind}
    >
      <PageBar title="History">
        <CredentialField
          hasToken={load.kind !== 'no_token'}
          rejected={load.kind === 'no_token' && getToken() !== null}
          onSave={onSave}
        />
      </PageBar>
      <main className="mx-auto w-full max-w-5xl space-y-3 px-3 py-3">
        {load.kind === 'no_token' && (
          <p className="text-[13px] text-muted">
            Enter your access token to read your history.
          </p>
        )}
        {load.kind === 'loading' && (
          <p className="text-[13px] text-muted">Loading the history.</p>
        )}
        {load.kind === 'error' && (
          <p className="notice notice-down text-[13px]" role="alert">
            {load.message}
          </p>
        )}
        {load.kind === 'ready' && (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <span
                className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted"
                data-testid="history-user"
              >
                {ownerLine(load.data, scope)}
              </span>
              {isAdmin && (
                <button
                  type="button"
                  className="btn"
                  data-testid="history-scope"
                  onClick={() => onScope(scope === 'all' ? 'own' : 'all')}
                >
                  {scope === 'all' ? 'Show mine' : 'Show every user'}
                </button>
              )}
            </div>
            {load.data.items.length === 0 &&
            load.data.role === 'visitor' &&
            load.data.user === KEYLESS_VISITOR ? (
              <div
                className="flex flex-wrap items-center gap-3 text-[13px] text-muted"
                data-testid="history-empty"
              >
                <span>
                  The history is kept per Anthropic API key. Add yours to keep
                  the questions you ask.
                </span>
                <button
                  type="button"
                  className="btn"
                  data-testid="history-add-key"
                  onClick={openApiKeySettings}
                >
                  Add API key
                </button>
              </div>
            ) : load.data.items.length === 0 ? (
              <p className="text-[13px] text-muted" data-testid="history-empty">
                No questions yet. Ask one on the question page.
              </p>
            ) : (
              <ol className="panel divide-y divide-line" aria-label="History">
                {load.data.items.map(item => (
                  <li
                    key={item.request_id}
                    className="space-y-1.5 px-3 py-2.5 hover:bg-raised"
                    data-testid="history-item"
                    data-request-id={item.request_id}
                  >
                    <p className="text-[13px] font-medium text-ink">
                      {item.question}
                    </p>
                    <p className="num text-[11px] text-muted">
                      {when(item.timestamp)}
                      {item.tickers.length > 0 &&
                        ` · ${item.tickers.join(', ')}`}
                      {item.outcome !== null && ` · ${item.outcome}`}
                      {` · $${item.cost_usd.toFixed(4)}`}
                      {scope === 'all' && ` · ${item.user ?? 'unknown user'}`}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        className="btn"
                        disabled={!item.stored}
                        title={
                          item.stored
                            ? undefined
                            : 'The answer is no longer stored; ask again.'
                        }
                        data-testid="history-open"
                        onClick={() =>
                          window.location.assign(sharePath(item.request_id))
                        }
                      >
                        Open answer
                      </button>
                      <button
                        type="button"
                        className="btn"
                        disabled={!item.stored}
                        data-testid="history-copy-link"
                        onClick={() => onCopy(item.request_id)}
                      >
                        {copied === item.request_id
                          ? 'Link copied'
                          : 'Copy link'}
                      </button>
                      <button
                        type="button"
                        className="btn"
                        data-testid="history-rerun"
                        onClick={() => {
                          writeSession(RERUN_QUESTION_KEY, item.question);
                          window.location.assign('/');
                        }}
                      >
                        Re-run
                      </button>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </main>
    </div>
  );
}
