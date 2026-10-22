import type {JSX} from 'react';

import type {AnswerCoverage} from '../api/types';

/** Props of CoverageIndicator. */
export interface CoverageIndicatorProps {
  readonly coverage: AnswerCoverage;
}

/**
 * The coverage indicator: 1 chip per company with the forms and periods
 * used, gray for an absent company.
 *
 * @param props The props.
 * @return The chip row.
 */
export function CoverageIndicator({
  coverage,
}: CoverageIndicatorProps): JSX.Element {
  return (
    <ul
      className="flex flex-wrap gap-2 text-xs"
      aria-label="Coverage"
      data-testid="coverage-indicator"
    >
      {coverage.companies_used.map(company => (
        <li
          key={company.ticker}
          className="rounded border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-emerald-900"
          data-covered="true"
        >
          {company.ticker}: {company.forms.join(', ')}{' '}
          {company.fiscal_periods.join(', ')}
        </li>
      ))}
      {coverage.companies_missing.map(ticker => (
        <li
          key={ticker}
          className="rounded border border-slate-300 bg-slate-100 px-2 py-0.5 text-slate-500"
          data-covered="false"
        >
          {ticker}: no filings
        </li>
      ))}
      {coverage.data_as_of !== '' && (
        <li className="px-1 py-0.5 text-slate-500">
          data as of {coverage.data_as_of}
        </li>
      )}
    </ul>
  );
}
