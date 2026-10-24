import type {JSX} from 'react';

import type {DirectoryCompany} from '../../api/types';
import {JobFeedback} from './JobFeedback';
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
 * marks, and the Add button that starts `keel add` with its ticker. The
 * row of the last Add shows the job card under it.
 *
 * @param props The company, the adder, and the indent.
 * @return The row, and the job row when this company was added.
 */
export function CompanyRow({
  company,
  adder,
  depth,
}: CompanyRowProps): JSX.Element {
  const isTarget = adder.target === company.ticker;
  const others = company.tickers.slice(1);
  const label = company.indexed ? 'Update' : 'Add';
  return (
    <>
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
        <td className="text-right">
          <button
            type="button"
            className={company.indexed ? 'btn' : 'btn btn-primary'}
            disabled={adder.busy || !company.addable}
            title={
              company.addable
                ? undefined
                : 'keel add takes letters and a share class only'
            }
            aria-label={`${label} ${company.ticker} (${company.name})`}
            data-testid="company-add"
            onClick={() => adder.add(company.ticker)}
          >
            {label}
          </button>
        </td>
      </tr>
      {isTarget && adder.state.kind !== 'idle' && (
        <tr data-testid="company-job">
          <td colSpan={BROWSER_COLUMNS} className="font-normal">
            <JobFeedback state={adder.state} onFinal={adder.onFinal} />
          </td>
        </tr>
      )}
    </>
  );
}
