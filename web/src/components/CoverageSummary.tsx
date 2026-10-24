import type {JSX} from 'react';

import type {CoverageResponse} from '../api/types';
import {financialsPath} from '../lib/links';

/** Props of CoverageSummary. */
export interface CoverageSummaryProps {
  readonly coverage: CoverageResponse | null;
  readonly hasToken: boolean;
}

/**
 * Formats the coverage summary line.
 *
 * @param coverage The coverage.
 * @return Text such as `54 companies, 245 filings, 1 quarantined`.
 */
export function coverageLine(coverage: CoverageResponse): string {
  const n = coverage.companies.length;
  const q = coverage.quarantined.length;
  return `${n} ${n === 1 ? 'company' : 'companies'}, ${coverage.filing_count} filings, ${q} quarantined`;
}

/**
 * The coverage summary of the empty state (table 14.6).
 *
 * @param props The props.
 * @return The summary.
 */
export function CoverageSummary({
  coverage,
  hasToken,
}: CoverageSummaryProps): JSX.Element {
  return (
    <section className="panel" aria-label="Coverage">
      <div className="panel-head">
        <h2 className="panel-title">Coverage</h2>
        <p
          className="num ml-auto text-[11px] text-ink-2"
          data-testid="coverage-summary"
        >
          {coverage !== null
            ? coverageLine(coverage)
            : hasToken
              ? 'Loading the coverage.'
              : 'Enter the access token to load the coverage.'}
        </p>
      </div>
      {coverage !== null && coverage.companies.length > 0 && (
        <div className="overflow-hidden">
          <ul
            className="-mb-px -mr-px grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3"
            aria-label="Covered companies"
            data-testid="coverage-companies"
          >
            {coverage.companies.map(company => (
              <li
                key={company.ticker}
                className="flex min-w-0 items-center gap-2 px-2.5 py-1.5 shadow-[inset_0_-1px_0_var(--k-line),inset_-1px_0_0_var(--k-line)] hover:bg-raised"
                title={company.fiscal_periods.join(', ')}
              >
                <a
                  className="w-12 shrink-0 font-mono text-[11.5px] font-semibold text-accent hover:underline"
                  href={financialsPath(company.ticker)}
                  title={`Financial statements of ${company.ticker}`}
                  data-testid="coverage-financials-link"
                >
                  {company.ticker}
                </a>
                <span className="min-w-0 truncate text-xs text-ink-2">
                  {company.company}
                </span>
                <span className="num ml-auto shrink-0 text-[10.5px] text-muted">
                  {company.forms.join(' ')}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
