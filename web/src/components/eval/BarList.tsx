import type {JSX} from 'react';
import {useId, useState} from 'react';

/** 1 bar of a BarList. */
export interface BarItem {
  readonly label: string;
  readonly value: number;
  /** True draws the bar in the accent color, else the quiet gray. */
  readonly emphasis: boolean;
  /** An extra line for the tooltip. */
  readonly detail?: string;
}

/** Props of BarList. */
export interface BarListProps {
  readonly title: string;
  /** 1 sentence on how to read the chart. */
  readonly caption: string;
  readonly items: readonly BarItem[];
  /** The value at the right end of the scale. */
  readonly max: number;
  readonly format: (value: number) => string;
  /** The format of the scale labels; the value format by default. */
  readonly tickFormat?: (value: number) => string;
  /** A target line, such as a gate, with its label. */
  readonly target?: {readonly value: number; readonly label: string};
  /** The legend names of the accent and the gray bars. */
  readonly legend: {readonly emphasis: string; readonly rest: string};
  readonly testId: string;
}

const TICKS = [0, 0.25, 0.5, 0.75, 1];

/**
 * A horizontal bar chart of 1 measure: 1 row per item, thin bars from a
 * shared baseline, hairline gridlines, an optional target line, and the
 * value as text beside each bar. Accent bars carry the point of the chart
 * (below a gate, or the setup in use); the rest are gray. Each row shows
 * a tooltip on hover and on keyboard focus; every value is also printed,
 * and the report table below holds the same numbers.
 *
 * @param props The chart.
 * @return The chart.
 */
export function BarList({
  title,
  caption,
  items,
  max,
  format,
  tickFormat = format,
  target,
  legend,
  testId,
}: BarListProps): JSX.Element {
  const [active, setActive] = useState<number | null>(null);
  const captionId = useId();
  const share = (value: number): number =>
    Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  const hasEmphasis = items.some(item => item.emphasis);
  const hasRest = items.some(item => !item.emphasis);
  return (
    <figure
      className="min-w-0 space-y-2"
      aria-labelledby={`${captionId}-title`}
      aria-describedby={captionId}
      data-testid={testId}
    >
      <div>
        <h3
          id={`${captionId}-title`}
          className="text-[13px] font-semibold text-ink"
        >
          {title}
        </h3>
        <p id={captionId} className="text-[12px] text-ink-2">
          {caption}
        </p>
      </div>
      {hasEmphasis && hasRest && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-ink-2">
          <li className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-[2px] bg-[var(--k-accent)]"
              aria-hidden="true"
            />
            {legend.emphasis}
          </li>
          <li className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-[2px] bg-[var(--k-deemph)]"
              aria-hidden="true"
            />
            {legend.rest}
          </li>
        </ul>
      )}
      <div className="grid grid-cols-[minmax(6rem,max-content)_minmax(0,1fr)_3.5rem] items-center gap-x-2">
        <span />
        <div className="relative h-4 text-[10px] text-muted" aria-hidden="true">
          {TICKS.map(tick => (
            <span
              key={tick}
              className="absolute -translate-x-1/2 whitespace-nowrap font-mono"
              style={{left: `${tick * 100}%`}}
            >
              {tickFormat(tick * max)}
            </span>
          ))}
        </div>
        <span />
        {items.map((item, index) => {
          const open = active === index;
          return (
            <div
              key={item.label}
              className="contents"
              data-testid={`${testId}-row`}
            >
              <span className="truncate whitespace-nowrap py-1 font-mono text-[11.5px] text-ink">
                {item.label}
              </span>
              <button
                type="button"
                className={`relative block h-6 w-full cursor-default rounded-[2px] text-left ${
                  open ? 'bg-raised' : ''
                }`}
                aria-label={`${item.label}: ${format(item.value)}${
                  item.detail === undefined ? '' : `, ${item.detail}`
                }`}
                onPointerEnter={() => setActive(index)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => setActive(index)}
                onBlur={() => setActive(null)}
              >
                {TICKS.map(tick => (
                  <span
                    key={tick}
                    className="absolute inset-y-0 w-px bg-[var(--k-line)]"
                    style={{left: `${tick * 100}%`}}
                    aria-hidden="true"
                  />
                ))}
                <span
                  className={`absolute left-0 top-1/2 h-3.5 -translate-y-1/2 rounded-r-[4px] ${
                    item.emphasis
                      ? 'bg-[var(--k-accent)]'
                      : 'bg-[var(--k-deemph)]'
                  } ${open ? 'brightness-110' : ''}`}
                  style={{width: `${share(item.value)}%`}}
                  aria-hidden="true"
                />
                {target !== undefined && (
                  <span
                    className="absolute inset-y-0 w-px bg-[var(--k-ink-2)]"
                    style={{left: `${share(target.value)}%`}}
                    aria-hidden="true"
                  />
                )}
                {open && (
                  <span
                    className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 -translate-x-1/2 whitespace-nowrap rounded-sm border border-line bg-panel px-2 py-1 text-[11.5px] shadow-md"
                    role="tooltip"
                  >
                    <span className="block font-semibold text-ink">
                      {format(item.value)}
                    </span>
                    <span className="block text-ink-2">{item.label}</span>
                    {item.detail !== undefined && (
                      <span className="block text-muted">{item.detail}</span>
                    )}
                  </span>
                )}
              </button>
              <span className="text-right font-mono text-[11.5px] text-ink">
                {format(item.value)}
              </span>
            </div>
          );
        })}
      </div>
      {target !== undefined && (
        <p className="flex items-center gap-1.5 text-[11.5px] text-ink-2">
          <span
            className="inline-block h-3 w-px bg-[var(--k-ink-2)]"
            aria-hidden="true"
          />
          {target.label}
        </p>
      )}
    </figure>
  );
}
