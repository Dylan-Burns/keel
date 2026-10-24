import type {JSX} from 'react';
import {useEffect, useState} from 'react';

import type {
  FilingSource,
  FinancialsItem,
  FinancialsPoint,
  FinancialsUnit,
} from '../../api/types';
import type {PeriodColumn, UnitChoice} from '../../lib/financials';
import {
  SCALES,
  formatDate,
  formatValue,
  periodRange,
  pointsByLabel,
  shortLabel,
} from '../../lib/financials';
import {BarChart} from './BarChart';
import type {TooltipContent} from './ChartTooltip';
import {ChartTooltip} from './ChartTooltip';

/** Props of StatementCharts. */
export interface StatementChartsProps {
  /** The rows of the statement. */
  readonly items: readonly FinancialsItem[];
  /** The checked rows and their color slots. */
  readonly checked: ReadonlyMap<string, number>;
  /** The shown periods, oldest first. */
  readonly periods: readonly PeriodColumn[];
  readonly unit: UnitChoice;
  readonly sources: readonly FilingSource[];
}

const UNIT_NAMES: Readonly<Record<FinancialsUnit, string>> = {
  USD: 'USD',
  'USD/shares': 'USD per share',
  shares: 'Shares',
};

/** The tooltip on show: its period, place, and whether it is pinned. */
interface Tip {
  readonly index: number;
  readonly x: number;
  readonly y: number;
  readonly pinned: boolean;
}

/**
 * The charts of a statement: a legend of the checked rows and 1 bar chart
 * per unit, stacked (dollars, per-share values, and share counts never
 * share a y axis), with 1 tooltip for every chart that lists each checked
 * row of the period with its source filing.
 *
 * @param props The props.
 * @return The legend and the charts.
 */
export function StatementCharts({
  items,
  checked,
  periods,
  unit,
  sources,
}: StatementChartsProps): JSX.Element {
  const [tip, setTip] = useState<Tip | null>(null);
  const pinned = tip?.pinned === true;
  useEffect(() => {
    if (!pinned) {
      return;
    }
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        setTip(null);
      }
    };
    const onDown = (event: globalThis.PointerEvent): void => {
      const target = event.target as Element | null;
      if (
        target?.closest('[data-testid="fin-tooltip"]') === null &&
        target.closest('[data-testid="fin-band"]') === null
      ) {
        setTip(null);
      }
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onDown);
    };
  }, [pinned]);

  const rows = [...checked.entries()]
    .map(([id, slot]) => ({item: items.find(i => i.id === id), slot}))
    .filter(
      (row): row is {item: FinancialsItem; slot: number} =>
        row.item !== undefined,
    );
  const maps = new Map(rows.map(r => [r.item.id, pointsByLabel(r.item)]));
  const units: FinancialsUnit[] = [];
  for (const row of rows) {
    if (!units.includes(row.item.unit)) {
      units.push(row.item.unit);
    }
  }
  const axis = periods.map(p => ({key: p.key, label: shortLabel(p.key)}));

  const contentOf = (index: number): TooltipContent | null => {
    const period = periods[index];
    if (period === undefined) {
      return null;
    }
    let first: FinancialsPoint | null = null;
    const lines = rows.map(({item, slot}) => {
      const point = maps.get(item.id)?.get(period.key) ?? null;
      first = first ?? point;
      const source = point === null ? undefined : sources[point.source];
      return {
        id: item.id,
        slot,
        label: item.label,
        value:
          point === null ? 'not reported' : formatValue(point.value, item.unit),
        source:
          source === undefined
            ? null
            : {
                form: source.form,
                filed: formatDate(source.filed),
                url: source.url,
              },
        derived: point?.derived === true,
        note: point?.note ?? null,
      };
    });
    return {
      title: period.key,
      subtitle: first === null ? '' : periodRange(first),
      rows: lines,
    };
  };

  if (rows.length === 0) {
    return (
      <p
        className="py-10 text-center text-[11px] text-muted"
        data-testid="fin-chart-empty"
      >
        Check a line item in the table to chart it.
      </p>
    );
  }
  const content = tip === null ? null : contentOf(tip.index);
  return (
    <div data-testid="fin-charts" data-series={rows.length}>
      <ul
        className="flex flex-wrap gap-x-3 gap-y-1 pb-1.5 text-[11px] text-ink-2"
        aria-label="Charted line items"
        data-testid="fin-legend"
      >
        {rows.map(({item, slot}) => (
          <li key={item.id} className="inline-flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-[2px]"
              style={{background: `var(--k-s${slot})`}}
              aria-hidden="true"
            />
            {item.label}
          </li>
        ))}
      </ul>
      {units.map((chartUnit, index) => (
        <div key={chartUnit} className={index > 0 ? 'mt-2.5' : ''}>
          {units.length > 1 && (
            <p className="section-title mb-0.5">{UNIT_NAMES[chartUnit]}</p>
          )}
          <BarChart
            periods={axis}
            unit={chartUnit}
            scale={unit === 'auto' ? null : SCALES[unit]}
            height={units.length > 1 ? (index > 0 ? 170 : 220) : 280}
            label={`${UNIT_NAMES[chartUnit]} bar chart of ${rows
              .filter(r => r.item.unit === chartUnit)
              .map(r => r.item.label)
              .join(', ')}`}
            series={rows
              .filter(r => r.item.unit === chartUnit)
              .map(({item, slot}) => {
                const map = maps.get(item.id);
                return {
                  id: item.id,
                  label: item.label,
                  slot,
                  values: periods.map(p => map?.get(p.key)?.value ?? null),
                  derived: periods.map(p => map?.get(p.key)?.derived === true),
                };
              })}
            active={tip?.index ?? null}
            onPeriod={(i, x, y, pin) => {
              if (pinned && !pin) {
                return;
              }
              setTip({index: i, x, y, pinned: pin});
            }}
            onLeave={() => {
              if (!pinned) {
                setTip(null);
              }
            }}
          />
        </div>
      ))}
      {tip !== null && content !== null && (
        <ChartTooltip
          content={content}
          x={tip.x}
          y={tip.y}
          pinned={tip.pinned}
          onClose={() => setTip(null)}
        />
      )}
    </div>
  );
}
