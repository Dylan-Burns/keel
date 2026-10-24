import type {JSX} from 'react';

import type {FinancialsPeriod} from '../../api/types';

/** Props of PeriodToggle. */
export interface PeriodToggleProps {
  readonly period: FinancialsPeriod;
  readonly onChange: (period: FinancialsPeriod) => void;
}

const OPTIONS: readonly (readonly [FinancialsPeriod, string])[] = [
  ['annual', 'Annual'],
  ['quarterly', 'Quarterly'],
];

/**
 * The Annual / Quarterly switch of the financials page.
 *
 * @param props The props.
 * @return The segmented control.
 */
export function PeriodToggle({
  period,
  onChange,
}: PeriodToggleProps): JSX.Element {
  return (
    <div className="segmented" role="group" aria-label="Period">
      {OPTIONS.map(([value, label]) => (
        <button
          key={value}
          type="button"
          className="segmented-option"
          aria-pressed={period === value}
          data-testid={`fin-period-${value}`}
          onClick={() => onChange(value)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
