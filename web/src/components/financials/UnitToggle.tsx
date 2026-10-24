import type {JSX} from 'react';

import type {UnitChoice} from '../../lib/financials';

/** Props of UnitToggle. */
export interface UnitToggleProps {
  readonly unit: UnitChoice;
  readonly onChange: (unit: UnitChoice) => void;
}

const OPTIONS: readonly (readonly [UnitChoice, string, string])[] = [
  ['auto', 'Auto', 'Scale each chart to its values'],
  ['K', 'K', 'Thousands'],
  ['M', 'M', 'Millions'],
  ['B', 'B', 'Billions'],
];

/**
 * The unit switch of the financials page: Auto, thousands, millions, or
 * billions for the dollar and share amounts. Per-share values stay in
 * dollars.
 *
 * @param props The props.
 * @return The segmented control.
 */
export function UnitToggle({unit, onChange}: UnitToggleProps): JSX.Element {
  return (
    <div className="segmented" role="group" aria-label="Units">
      {OPTIONS.map(([value, label, title]) => (
        <button
          key={value}
          type="button"
          className="segmented-option"
          aria-pressed={unit === value}
          title={title}
          data-testid={`fin-unit-${value}`}
          onClick={() => onChange(value)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
