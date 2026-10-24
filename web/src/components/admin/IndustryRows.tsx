import type {JSX} from 'react';

import type {DirectoryIndustry, IndustryCompanies} from '../../api/types';
import {BROWSER_COLUMNS, CompanyRow} from './CompanyRow';
import {TreeToggle} from './TreeToggle';
import type {CompanyAdder} from './useCompanyAdder';

/** The load state of the companies of 1 industry. */
export type IndustryLoad =
  | {readonly kind: 'loading'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly data: IndustryCompanies};

/** Props of IndustryRows. */
export interface IndustryRowsProps {
  readonly industry: DirectoryIndustry;
  readonly open: boolean;
  /** The companies once asked for; undefined before the first expand. */
  readonly load: IndustryLoad | undefined;
  readonly adder: CompanyAdder;
  /** Opens or closes the industry; opening loads its companies. */
  readonly onToggle: (code: string) => void;
  /** Asks for the companies again after an error. */
  readonly onRetry: (code: string) => void;
}

/**
 * The words of the company count of an industry.
 *
 * @param count The companies, or null before the list is cached.
 * @return The text; empty before the first load.
 */
function countWords(count: number | null): string {
  if (count === null) {
    return '';
  }
  return count === 1 ? '1 company' : `${count} companies`;
}

/**
 * 1 industry (an SEC SIC code) and, when open, its companies: a loading
 * row, an error row with a retry, or 1 row per company with a ticker.
 *
 * @param props The industry, its state, and the actions.
 * @return The rows.
 */
export function IndustryRows({
  industry,
  open,
  load,
  adder,
  onToggle,
  onRetry,
}: IndustryRowsProps): JSX.Element {
  const count =
    load?.kind === 'ready' ? load.data.companies.length : industry.companies;
  return (
    <>
      <tr data-testid="industry-row" data-code={industry.code}>
        <td colSpan={BROWSER_COLUMNS} className="pl-6">
          <TreeToggle
            open={open}
            testId="industry-toggle"
            onToggle={() => onToggle(industry.code)}
          >
            <span className="tag shrink-0">{industry.code}</span>
            <span className="min-w-0 flex-1 break-words font-normal text-ink">
              {industry.title}
            </span>
            <span className="shrink-0 font-mono text-[10.5px] font-normal text-muted">
              {countWords(count)}
            </span>
          </TreeToggle>
        </td>
      </tr>
      {open && load?.kind === 'loading' && (
        <tr data-testid="industry-loading">
          <td colSpan={BROWSER_COLUMNS} className="pl-12 font-normal">
            <span className="text-muted" role="status">
              Loading the companies from SEC EDGAR.
            </span>
          </td>
        </tr>
      )}
      {open && load?.kind === 'error' && (
        <tr data-testid="industry-error">
          <td colSpan={BROWSER_COLUMNS} className="pl-12 font-normal">
            <span className="text-down" role="alert">
              {load.message}
            </span>{' '}
            <button
              type="button"
              className="btn"
              data-testid="industry-retry"
              onClick={() => onRetry(industry.code)}
            >
              Retry
            </button>
          </td>
        </tr>
      )}
      {open && load?.kind === 'ready' && load.data.companies.length === 0 && (
        <tr data-testid="industry-empty">
          <td
            colSpan={BROWSER_COLUMNS}
            className="pl-12 font-normal text-muted"
          >
            No company of this industry has a ticker.
          </td>
        </tr>
      )}
      {open &&
        load?.kind === 'ready' &&
        load.data.companies.map(company => (
          <CompanyRow
            key={company.cik}
            company={company}
            adder={adder}
            depth={2}
          />
        ))}
    </>
  );
}
