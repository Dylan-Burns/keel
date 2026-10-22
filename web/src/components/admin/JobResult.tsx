import type {JSX} from 'react';

import {scalar} from '../../lib/format';
import type {Row} from './MiniTable';
import {MiniTable} from './MiniTable';

/** Props of JobResult. */
export interface JobResultProps {
  /** The `result` object of a succeeded job. */
  readonly result: Readonly<Record<string, unknown>>;
}

/**
 * The rows of an array field, when every item is an object.
 *
 * @param value The field.
 * @return The rows, or null.
 */
function rowsOf(value: unknown): readonly Row[] | null {
  return Array.isArray(value) &&
    value.every(v => typeof v === 'object' && v !== null && !Array.isArray(v))
    ? (value as Row[])
    : null;
}

/**
 * The summary of a succeeded job: the facts lines of `facts`, the per
 * ticker check of `refresh` (with the new filings of a dry run), the
 * filings of `add`, the gates of `eval`, and the scalar fields of every
 * kind as a key and value grid. Every value renders as a JSX text node.
 *
 * @param props The props.
 * @return The result.
 */
export function JobResult({result}: JobResultProps): JSX.Element {
  const lines = result['lines'];
  const tickers = rowsOf(result['tickers']);
  const filings = rowsOf(result['filings']);
  const gates = rowsOf(result['gates']);
  const shown = new Set(['lines', 'tickers', 'filings', 'gates']);
  const entries = Object.entries(result).filter(
    ([key, value]) =>
      !shown.has(key) && (typeof value !== 'object' || value === null),
  );
  const nested = Object.entries(result).filter(
    ([key, value]) =>
      !shown.has(key) && typeof value === 'object' && value !== null,
  );
  return (
    <div className="space-y-2" data-testid="job-result">
      {entries.length > 0 && (
        <dl className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-x-3 gap-y-0.5 font-mono text-[11.5px]">
          {entries.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="truncate text-muted">{key.replace(/_/g, ' ')}</dt>
              <dd className="break-words text-ink">{scalar(value)}</dd>
            </div>
          ))}
          {nested.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="truncate text-muted">{key.replace(/_/g, ' ')}</dt>
              <dd className="break-words text-ink">{scalar(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {Array.isArray(lines) && (
        <pre
          className="max-h-72 overflow-auto whitespace-pre-wrap border border-line bg-field p-2 font-mono text-[11.5px] text-ink-2"
          data-testid="job-result-lines"
        >
          {lines.map(String).join('\n')}
        </pre>
      )}
      {tickers !== null && (
        <MiniTable
          caption="Tickers checked"
          columns={['ticker', 'new', 'added', 'error']}
          testId="job-result-tickers"
          rows={tickers.map(row => ({
            ticker: row['ticker'],
            new:
              rowsOf(row['new'])
                ?.map(
                  f => `${scalar(f['form'])} filed ${scalar(f['filing_date'])}`,
                )
                .join('; ') || 'up to date',
            added: rowsOf(row['added'])?.length ?? 0,
            error: row['error'] ?? '',
          }))}
        />
      )}
      {filings !== null && (
        <MiniTable
          caption="Filings"
          columns={['form', 'filing_date', 'file_name', 'chunks', 'quarantine']}
          rows={filings}
          testId="job-result-filings"
        />
      )}
      {gates !== null && (
        <MiniTable
          caption="Gates"
          columns={['name', 'value', 'status']}
          rows={gates}
          testId="job-result-gates"
        />
      )}
    </div>
  );
}
