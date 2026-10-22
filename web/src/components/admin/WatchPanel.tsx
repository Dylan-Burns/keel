import type {JSX} from 'react';
import {useEffect, useState} from 'react';

import {addWatch, fetchWatch, removeWatch} from '../../api/admin';
import {ApiError} from '../../api/client';
import type {WatchItem, WatchList} from '../../api/types';
import {OpsPanelHead} from './OpsPanelHead';
import {tickersOf} from './tickers';

/** The load state of the watch list. */
type Load =
  | {readonly kind: 'loading'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly data: WatchList};

/**
 * The key of a watch row.
 *
 * @param item The row.
 * @return The ticker and the user.
 */
function rowKey(item: WatchItem): string {
  return `${item.ticker}:${item.user ?? ''}:${item.added_date}:${String(item.mine)}`;
}

/** Props of WatchPanel. */
export interface WatchPanelProps {
  /** True for an admin: the add and remove controls show. */
  readonly isAdmin: boolean;
  /** A counter the page bumps to reload the list. */
  readonly version: number;
}

/**
 * The watch list: every user reads it; an admin adds tickers and removes a
 * row after an inline confirmation.
 *
 * @param props The role and the reload counter.
 * @return The panel.
 */
export function WatchPanel({isAdmin, version}: WatchPanelProps): JSX.Element {
  const [load, setLoad] = useState<Load>({kind: 'loading'});
  const [own, setOwn] = useState(0);
  const [tickers, setTickers] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetchWatch()
      .then(data => {
        if (!cancelled) {
          setLoad({kind: 'ready', data});
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoad({kind: 'error', message: 'The watch list could not load.'});
        }
      });
    return () => {
      cancelled = true;
    };
  }, [version, own]);
  const onAdd = (): void => {
    const list = tickersOf(tickers);
    if (list.length === 0 || list.length > 25) {
      setNotice('Give 1 to 25 tickers.');
      return;
    }
    setSending(true);
    addWatch(list)
      .then(added => {
        const parts = [
          added.added.length > 0 ? `Watching ${added.added.join(', ')}.` : '',
          added.unchanged.length > 0
            ? `Already watched: ${added.unchanged.join(', ')}.`
            : '',
        ].filter(Boolean);
        setNotice(parts.join(' '));
        setTickers('');
        setOwn(n => n + 1);
      })
      .catch((error: unknown) =>
        setNotice(
          error instanceof ApiError
            ? error.message
            : 'The tickers could not be added.',
        ),
      )
      .finally(() => setSending(false));
  };
  const onRemove = (item: WatchItem): void => {
    removeWatch(item.ticker, item.user)
      .then(() => {
        setNotice(`Stopped watching ${item.ticker}.`);
        setRemoving(null);
        setOwn(n => n + 1);
      })
      .catch(() => {
        setNotice(`${item.ticker} could not be removed.`);
        setRemoving(null);
      });
  };
  return (
    <section className="panel" aria-label="Watch list" data-testid="watch">
      <OpsPanelHead title="Watch list" note="keel watch" />
      <div className="panel-body space-y-3">
        <p className="text-[12.5px] text-ink-2">
          The refresh checks the union of every user&apos;s tickers.
          {isAdmin ? '' : ' An admin adds and removes tickers.'}
        </p>
        {isAdmin && (
          <form
            className="flex flex-wrap items-end gap-2"
            data-testid="watch-form"
            onSubmit={event => {
              event.preventDefault();
              onAdd();
            }}
          >
            <label className="flex min-w-0 flex-col gap-1">
              <span className="section-title">Tickers to watch</span>
              <input
                className="input w-72 max-w-full font-mono uppercase"
                value={tickers}
                placeholder="ZTS, WDAY"
                autoComplete="off"
                data-testid="watch-tickers"
                onChange={event => setTickers(event.target.value)}
              />
            </label>
            <button
              type="submit"
              className="btn"
              disabled={sending}
              data-testid="watch-add"
            >
              Watch
            </button>
          </form>
        )}
        {notice !== null && (
          <p
            className="font-mono text-[12px] text-ink-2"
            role="status"
            data-testid="watch-notice"
          >
            {notice}
          </p>
        )}
        {load.kind === 'loading' && (
          <p className="text-[12px] text-muted">Loading the watch list.</p>
        )}
        {load.kind === 'error' && (
          <p className="text-[12px] text-down" role="alert">
            {load.message}
          </p>
        )}
        {load.kind === 'ready' && load.data.items.length === 0 && (
          <p className="text-[12px] text-muted" data-testid="watch-empty">
            Nobody watches a ticker yet.
          </p>
        )}
        {load.kind === 'ready' && load.data.items.length > 0 && (
          <div className="overflow-x-auto border border-line">
            <table className="grid-table" data-testid="watch-table">
              <thead>
                <tr>
                  <th scope="col">Ticker</th>
                  <th scope="col">User</th>
                  <th scope="col">Added</th>
                  {isAdmin && (
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {load.data.items.map(item => (
                  <tr
                    key={rowKey(item)}
                    data-testid="watch-row"
                    data-ticker={item.ticker}
                  >
                    <td className="font-mono">{item.ticker}</td>
                    <td className="font-mono text-[11.5px] text-ink-2">
                      {item.user ?? (item.mine ? 'you' : 'another user')}
                    </td>
                    <td className="num text-[11.5px] text-ink-2">
                      {item.added_date}
                    </td>
                    {isAdmin && (
                      <td className="text-right">
                        {removing === rowKey(item) ? (
                          <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                            <span className="text-[12px] text-ink-2">
                              Stop watching {item.ticker}?
                            </span>
                            <button
                              type="button"
                              className="btn btn-danger"
                              data-testid="watch-remove-confirm"
                              onClick={() => onRemove(item)}
                            >
                              Remove
                            </button>
                            <button
                              type="button"
                              className="btn"
                              onClick={() => setRemoving(null)}
                            >
                              Keep
                            </button>
                          </span>
                        ) : (
                          <button
                            type="button"
                            className="btn"
                            aria-label={`Remove ${item.ticker} from the watch list`}
                            data-testid="watch-remove"
                            onClick={() => setRemoving(rowKey(item))}
                          >
                            Remove
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
