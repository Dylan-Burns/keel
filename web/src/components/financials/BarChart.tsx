import {motion, useReducedMotion} from 'motion/react';
import type {JSX, KeyboardEvent, PointerEvent, RefObject} from 'react';
import {useEffect, useRef, useState} from 'react';

import type {FinancialsUnit} from '../../api/types';
import type {Scale} from '../../lib/financials';
import {
  SCALES,
  autoScale,
  barPath,
  niceTicks,
  tickText,
} from '../../lib/financials';
import {financials, pick} from '../../motion/presets';

/** 1 bar series: a checked row. */
export interface BarSeries {
  readonly id: string;
  readonly label: string;
  /** The color slot, 1 to 8. */
  readonly slot: number;
  /** The value per period, null when not reported. */
  readonly values: readonly (number | null)[];
  /** True per period for a derived value (drawn faded). */
  readonly derived: readonly boolean[];
}

/** 1 period of the x axis. */
export interface BarPeriod {
  readonly key: string;
  /** The axis label. */
  readonly label: string;
}

/** Props of BarChart. */
export interface BarChartProps {
  readonly periods: readonly BarPeriod[];
  readonly series: readonly BarSeries[];
  readonly unit: FinancialsUnit;
  /** The axis scale, or null to pick one from the values. */
  readonly scale: Scale | null;
  readonly height: number;
  /** The accessible name of the chart. */
  readonly label: string;
  /** The period under the pointer or the focus, in every chart. */
  readonly active: number | null;
  /**
   * A period is hovered, focused, or picked.
   *
   * @param index The period.
   * @param x The viewport x of the tooltip anchor.
   * @param y The viewport y of the tooltip anchor.
   * @param pin True for a click or Enter: pin the tooltip.
   */
  readonly onPeriod: (
    index: number,
    x: number,
    y: number,
    pin: boolean,
  ) => void;
  /** The pointer or the focus left the chart. */
  readonly onLeave: () => void;
}

const MARGIN = {left: 52, right: 10, top: 14, bottom: 22};
const FALLBACK_WIDTH = 720;
const CHAR_WIDTH = 6.2;

/**
 * Follows the width of an element (a fallback width without
 * ResizeObserver, as in jsdom).
 *
 * @return The ref to attach and the width.
 */
function useWidth(): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(FALLBACK_WIDTH);
  useEffect(() => {
    const node = ref.current;
    if (node === null || typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver(() => {
      if (node.clientWidth > 0) {
        setWidth(node.clientWidth);
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/**
 * A grouped bar chart in SVG: 1 bar per checked row in each period, the
 * row's palette color, a derived value faded, with a y axis of round ticks
 * and gridlines, and x labels thinned so they never collide. Each period is
 * a focusable band: hover or focus shows the tooltip, a click or Enter pins
 * it, and the arrow keys move between periods.
 *
 * @param props The props.
 * @return The chart.
 */
export function BarChart({
  periods,
  series,
  unit,
  scale,
  height,
  label,
  active,
  onPeriod,
  onLeave,
}: BarChartProps): JSX.Element {
  const reduced = useReducedMotion();
  const [ref, width] = useWidth();
  const bands = useRef<(SVGRectElement | null)[]>([]);
  const count = periods.length;
  const plotWidth = Math.max(10, width - MARGIN.left - MARGIN.right);
  const plotHeight = Math.max(10, height - MARGIN.top - MARGIN.bottom);
  const values = series
    .flatMap(s => s.values)
    .filter((v): v is number => v !== null && Number.isFinite(v));
  const maxAbs = Math.max(0, ...values.map(Math.abs));
  const axisScale =
    unit === 'USD/shares' ? SCALES[''] : (scale ?? autoScale(maxAbs));
  const ticks = niceTicks(
    Math.min(0, ...values),
    Math.max(0, ...values),
    Math.max(3, Math.round(plotHeight / 48)),
  );
  const low = ticks[0] ?? 0;
  const high = ticks[ticks.length - 1] ?? 1;
  const y = (v: number): number =>
    MARGIN.top + plotHeight - ((v - low) / (high - low || 1)) * plotHeight;
  const band = plotWidth / Math.max(1, count);
  const center = (i: number): number => MARGIN.left + band * i + band / 2;
  const labelWidth =
    Math.max(0, ...periods.map(p => p.label.length)) * CHAR_WIDTH + 8;
  const every = Math.max(1, Math.ceil(labelWidth / band));
  const k = series.length;
  const inner = Math.min(band * 0.78, k * 38);
  const gap = k > 1 ? Math.min(2, inner / k / 4) : 0;
  const barWidth = Math.max(1, (inner - gap * (k - 1)) / Math.max(1, k));
  const signature = `${series.map(s => s.id).join(',')}|${periods
    .map(p => p.key)
    .join(',')}`;

  const anchor = (
    index: number,
    event: PointerEvent<SVGRectElement> | null,
  ): [number, number] => {
    if (event !== null) {
      return [event.clientX, event.clientY];
    }
    const box = bands.current[index]?.getBoundingClientRect();
    return box === undefined
      ? [0, 0]
      : [box.left + box.width / 2, box.top + 20];
  };
  const onKey = (index: number, event: KeyboardEvent<SVGRectElement>): void => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      const [x, yy] = anchor(index, null);
      onPeriod(index, x, yy, true);
    } else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      const next = index + (event.key === 'ArrowRight' ? 1 : -1);
      bands.current[Math.min(count - 1, Math.max(0, next))]?.focus();
    }
  };

  return (
    <div
      ref={ref}
      className="fin-chart"
      data-testid="fin-chart"
      data-unit={unit}
      data-series={k}
    >
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label={label}
      >
        <g aria-hidden="true">
          {ticks.map(t => (
            <g key={t}>
              <line
                x1={MARGIN.left}
                x2={MARGIN.left + plotWidth}
                y1={y(t)}
                y2={y(t)}
                className={t === 0 ? 'fin-zero' : 'fin-grid'}
              />
              <text x={MARGIN.left - 6} y={y(t) + 3} textAnchor="end">
                {tickText(t, unit, axisScale, ticks)}
              </text>
            </g>
          ))}
          {periods.map((p, i) =>
            (count - 1 - i) % every === 0 ? (
              <text
                key={p.key}
                x={center(i)}
                y={MARGIN.top + plotHeight + 14}
                textAnchor="middle"
              >
                {p.label}
              </text>
            ) : null,
          )}
        </g>
        <g>
          {periods.map((p, i) => (
            <rect
              key={p.key}
              ref={node => {
                bands.current[i] = node;
              }}
              x={MARGIN.left + band * i}
              y={MARGIN.top}
              width={band}
              height={plotHeight}
              className="fin-band"
              data-on={active === i}
              data-testid="fin-band"
              tabIndex={0}
              role="button"
              aria-label={`${p.key}: show the values`}
              onPointerMove={event => {
                const [x, yy] = anchor(i, event);
                onPeriod(i, x, yy, false);
              }}
              onPointerLeave={onLeave}
              onClick={event => {
                onPeriod(i, event.clientX, event.clientY, true);
              }}
              onFocus={() => {
                const [x, yy] = anchor(i, null);
                onPeriod(i, x, yy, false);
              }}
              onBlur={onLeave}
              onKeyDown={event => onKey(i, event)}
            />
          ))}
        </g>
        <motion.g
          key={signature}
          className="pointer-events-none"
          variants={pick(financials.bars, reduced)}
          initial="hidden"
          animate="visible"
          aria-hidden="true"
        >
          {series.map((s, j) =>
            s.values.map((v, i) => {
              if (v === null) {
                return null;
              }
              const x = center(i) - inner / 2 + j * (barWidth + gap);
              const d = barPath(
                x,
                y(0),
                y(v),
                barWidth,
                Math.min(4, barWidth / 3),
              );
              return d === '' ? null : (
                <path
                  key={`${s.id}:${i}`}
                  d={d}
                  data-testid="fin-bar"
                  data-series-id={s.id}
                  style={{
                    fill: `var(--k-s${s.slot})`,
                    fillOpacity: s.derived[i] === true ? 0.55 : 1,
                  }}
                />
              );
            }),
          )}
        </motion.g>
      </svg>
    </div>
  );
}
