import type {JSX} from 'react';

import type {CoverageResponse} from '../api/types';
import type {Example} from '../lib/examples';
import {ExampleChips} from './ExampleChips';

/** Props of OutOfScopeCard. */
export interface OutOfScopeCardProps {
  readonly reason: string;
  readonly coverage: CoverageResponse | null;
  readonly examples: readonly Example[];
  readonly askEnabled: boolean;
  readonly onPick: (example: Example) => void;
}

/**
 * The gray out-of-scope card: the reason, the covered companies, and the
 * example chips (table 14.6).
 *
 * @param props The props.
 * @return The card.
 */
export function OutOfScopeCard({
  reason,
  coverage,
  examples,
  askEnabled,
  onPick,
}: OutOfScopeCardProps): JSX.Element {
  return (
    <section
      className="space-y-3 rounded-lg border border-slate-300 bg-slate-100 p-4 text-sm text-slate-800"
      data-testid="card-out-of-scope"
    >
      <h2 className="font-medium">Outside what the filings answer</h2>
      <p>{reason}</p>
      {coverage !== null && coverage.companies.length > 0 && (
        <p className="text-xs text-slate-600">
          Covered companies: {coverage.companies.map(c => c.ticker).join(', ')}
        </p>
      )}
      <ExampleChips
        examples={examples}
        disabled={!askEnabled}
        onPick={onPick}
      />
    </section>
  );
}
