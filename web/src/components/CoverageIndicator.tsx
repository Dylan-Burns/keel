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
      className="flex flex-wrap items-center gap-1.5"
      aria-label="Coverage"
      data-testid="coverage-indicator"
    >
      {coverage.companies_used.map(company => (
        <li key={company.ticker} className="tag tag-up" data-covered="true">
          {company.ticker}: {company.forms.join(', ')}{' '}
          {company.fiscal_periods.join(', ')}
        </li>
      ))}
      {coverage.companies_missing.map(ticker => (
        <li key={ticker} className="tag tag-down" data-covered="false">
          {ticker}: no filings
        </li>
      ))}
      {coverage.data_as_of !== '' && (
        <li className="num text-[11px] text-muted">
          data as of {coverage.data_as_of}
        </li>
      )}
    </ul>
  );
}
