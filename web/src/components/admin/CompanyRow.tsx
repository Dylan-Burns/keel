import type {JSX} from 'react';

import type {DirectoryCompany} from '../../api/types';
import {financialsPath, jobPath} from '../../lib/links';
import type {CompanyAdder} from './useCompanyAdder';

/** The columns of the browser table: name, ticker, CIK, marks, action. */
export const BROWSER_COLUMNS = 5;

/** Props of CompanyRow. */
export interface CompanyRowProps {
  readonly company: DirectoryCompany;
  readonly adder: CompanyAdder;
  /** The indent: 0 in the search results, 2 under an industry. */
  readonly depth: 0 | 2;
}

/**
 * 1 company of the browser: name, ticker, CIK, the Indexed and Watched
 * marks, a link to the financials page of an indexed company, and the Add
 * button that starts `keel add` with its ticker. While the job of the row
 * runs, its button reads Adding (or Updating) with a spinner; a failed job
 * leaves a Failed tag that links to the job. The table never grows a row.
 *
 * @param props The company, the adder, and the indent.
 * @return The row.
 */
export function CompanyRow({
  company,
  adder,
  depth,
}: CompanyRowProps): JSX.Element {
  const outcome = adder.target === company.ticker ? adder.outcome : null;
  const running = outcome?.kind === 'running';
  const failure = outcome?.kind === 'failed' ? outcome : null;
  const others = company.tickers.slice(1);
  const label = company.indexed ? 'Update' : 'Add';
  const shown = running ? (company.indexed ? 'Updating' : 'Adding') : label;
  return (
    <tr data-testid="company-row" data-ticker={company.ticker}>
      <td className={depth === 2 ? 'pl-12' : ''}>
        <span className="block min-w-0 break-words font-normal">
          {company.name}
        </span>
        <span className="whitespace-nowrap font-mono text-[10.5px] text-muted sm:hidden">
          CIK {company.cik}
        </span>
      </td>
      <td className="font-mono">
        {company.ticker}
        {others.length > 0 && (
          <span className="block text-[10.5px] text-muted">
            {others.join(' ')}
          </span>
        )}
      </td>
      <td className="num hidden text-[11.5px] text-ink-2 sm:table-cell">
        {company.cik}
      </td>
      <td>
        <span className="inline-flex flex-wrap gap-1">
          {company.indexed && (
            <span className="tag tag-up" data-testid="badge-indexed">
              Indexed
            </span>
          )}
          {company.watched && (
            <span className="tag tag-accent" data-testid="badge-watched">
              Watched
            </span>
          )}
        </span>
      </td>
      <td className="whitespace-nowrap text-right">
        {company.indexed && (
          <a
            className="btn mr-1.5"
            href={financialsPath(company.ticker)}
            aria-label={`Financials of ${company.ticker} (${company.name})`}
            data-testid="company-financials"
          >
            Financials
          </a>
        )}
        {failure !== null && (
          <a
            className="tag tag-down mr-1.5"
            href={failure.jobId === null ? undefined : jobPath(failure.jobId)}
            title={failure.message}
            aria-label={`${label} ${company.ticker} failed: ${failure.message}`}
            data-testid="company-add-failed"
          >
            Failed
          </a>
        )}
        <button
          type="button"
          className={company.indexed ? 'btn' : 'btn btn-primary'}
          disabled={adder.busy || !company.addable}
          aria-busy={running}
          title={
            company.addable
              ? undefined
              : 'keel add takes letters and a share class only'
          }
          aria-label={`${shown} ${company.ticker} (${company.name})`}
          data-testid="company-add"
          onClick={() => adder.add(company.ticker)}
        >
          {running ? (
            <span
              className="inline-flex items-center gap-1.5"
              role="status"
              data-testid="company-adding"
            >
              <span
                className="size-3 rounded-full border-2 border-current border-t-transparent motion-safe:animate-spin"
                aria-hidden="true"
              />
              {shown}
            </span>
          ) : (
            label
          )}
        </button>
      </td>
    </tr>
  );
}
