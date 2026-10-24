import type {JSX} from 'react';

/** Props of RangeSlider. */
export interface RangeSliderProps {
  /** The number of periods. */
  readonly count: number;
  /** The first shown period. */
  readonly low: number;
  /** The last shown period. */
  readonly high: number;
  /** The label of a period index. */
  readonly labelOf: (index: number) => string;
  readonly onChange: (low: number, high: number) => void;
}

/**
 * The 2-thumb range slider of the financials page: the first and the last
 * period of the chart and the table. A thumb never passes the other.
 *
 * @param props The props.
 * @return The slider row.
 */
export function RangeSlider({
  count,
  low,
  high,
  labelOf,
  onChange,
}: RangeSliderProps): JSX.Element {
  const max = Math.max(0, count - 1);
  const percent = (value: number): number =>
    count > 1 ? (value / max) * 100 : 0;
  return (
    <div
      className="grid grid-cols-[auto_1fr_auto] items-center gap-2 px-2.5 pb-2 pt-1"
      data-testid="fin-range"
    >
      <span className="num min-w-16 text-[11px] text-ink-2">
        {labelOf(low)}
      </span>
      <div className="fin-range">
        <div className="fin-range-track" />
        <div
          className="fin-range-fill"
          style={{
            left: `${percent(low)}%`,
            width: `${percent(high) - percent(low)}%`,
          }}
        />
        <input
          type="range"
          min={0}
          max={max}
          step={1}
          value={low}
          aria-label="First period"
          aria-valuetext={labelOf(low)}
          data-testid="fin-range-low"
          onChange={event =>
            onChange(Math.min(Number(event.target.value), high), high)
          }
        />
        <input
          type="range"
          min={0}
          max={max}
          step={1}
          value={high}
          aria-label="Last period"
          aria-valuetext={labelOf(high)}
          data-testid="fin-range-high"
          onChange={event =>
            onChange(low, Math.max(Number(event.target.value), low))
          }
        />
      </div>
      <span className="num min-w-16 text-right text-[11px] text-ink-2">
        {labelOf(high)}
      </span>
    </div>
  );
}
