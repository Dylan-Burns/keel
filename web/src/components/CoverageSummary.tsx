import type {JSX} from 'react';

import type {CoverageResponse} from '../api/types';

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
    <p className="text-sm text-slate-600" data-testid="coverage-summary">
      {coverage !== null
        ? coverageLine(coverage)
        : hasToken
          ? 'Loading the coverage.'
          : 'Enter the access token to load the coverage.'}
    </p>
  );
}
