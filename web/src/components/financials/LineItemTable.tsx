import type {JSX} from 'react';
import {useLayoutEffect, useRef} from 'react';

import type {FilingSource, FinancialsItem} from '../../api/types';
import type {PeriodColumn, Scale} from '../../lib/financials';
import {
  MAX_SERIES,
  cellText,
  formatDate,
  formatValue,
  perShareDigits,
  pointsByLabel,
  treeRows,
} from '../../lib/financials';

/** Props of LineItemTable. */
export interface LineItemTableProps {
  /** The rows of the statement, in order. */
  readonly items: readonly FinancialsItem[];
  /** The shown periods, oldest first. */
  readonly periods: readonly PeriodColumn[];
  /** The checked rows and their color slots. */
  readonly checked: ReadonlyMap<string, number>;
  /** The expanded parent rows. */
  readonly expanded: ReadonlySet<string>;
  /** The scale of the dollar cells. */
  readonly usdScale: Scale;
  /** The scale of the share count cells. */
  readonly sharesScale: Scale;
  readonly sources: readonly FilingSource[];
  readonly onToggleCheck: (id: string) => void;
  readonly onToggleExpand: (id: string) => void;
}

/**
 * The line items of a statement as a table: 1 row per item with a check
 * box that charts it (filled with the series color once checked, 8 at
 * most), a caret that opens the child rows, and 1 column per period. A
 * derived value is italic with a star; each cell's title names its filing.
 * The label column stays put while the periods scroll, and the table opens
 * scrolled to the latest period.
 *
 * @param props The props.
 * @return The table.
 */
export function LineItemTable({
  items,
  periods,
  checked,
  expanded,
  usdScale,
  sharesScale,
  sources,
  onToggleCheck,
  onToggleExpand,
}: LineItemTableProps): JSX.Element {
  const wrap = useRef<HTMLDivElement>(null);
  const columns = periods.map(p => p.key).join(',');
  useLayoutEffect(() => {
    const node = wrap.current;
    if (node !== null) {
      node.scrollLeft = node.scrollWidth;
    }
  }, [columns]);
  const full = checked.size >= MAX_SERIES;
  return (
    <div
      ref={wrap}
      className="overflow-x-auto border-t border-line"
      data-testid="fin-table-wrap"
    >
      <table
        className="w-full border-separate border-spacing-0 text-[12px]"
        data-testid="fin-table"
      >
        <thead>
          <tr>
            <th
              scope="col"
              className="sticky left-0 z-[2] border-b border-r border-line bg-head px-2.5 py-1.5 text-left text-[10px] font-bold uppercase tracking-[0.06em] text-muted"
            >
              Breakdown
            </th>
            {periods.map(p => (
              <th
                key={p.key}
                scope="col"
                className="num whitespace-nowrap border-b border-line bg-head px-2.5 py-1.5 text-right text-[10px] font-bold uppercase tracking-[0.06em] text-muted"
              >
                {p.key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {treeRows(items, expanded).map(({item, depth, parent}) => {
            const slot = checked.get(item.id);
            const isChecked = slot !== undefined;
            const disabled = !isChecked && full;
            const open = expanded.has(item.id);
            const map = pointsByLabel(item);
            const shown = periods
              .map(p => map.get(p.key)?.value)
              .filter((v): v is number => v !== undefined);
            // Small per-share values keep their own decimals; the rest
            // read as cents.
            const digits =
              Math.max(0, ...shown.map(Math.abs)) < 0.1
                ? perShareDigits(shown)
                : 2;
            const scale = item.unit === 'shares' ? sharesScale : usdScale;
            return (
              <tr
                key={item.id}
                className="group"
                data-testid="fin-row"
                data-row={item.id}
                data-checked={isChecked}
              >
                <th
                  scope="row"
                  className={`sticky left-0 z-[1] whitespace-nowrap border-b border-r border-line bg-panel py-1.5 pr-2.5 text-left group-hover:bg-raised ${
                    isChecked ? 'font-semibold text-ink' : 'font-normal'
                  } ${depth > 0 ? 'text-ink-2' : 'text-ink'}`}
                  style={{paddingLeft: `${10 + depth * 24}px`}}
                >
                  <span className="flex items-center gap-1.5">
                    {parent ? (
                      <button
                        type="button"
                        className="w-3.5 shrink-0 text-[10px] text-muted hover:text-ink"
                        aria-expanded={open}
                        aria-label={`${open ? 'Collapse' : 'Expand'} ${item.label}`}
                        data-testid="fin-expand"
                        onClick={() => onToggleExpand(item.id)}
                      >
                        {open ? '▼' : '▶'}
                      </button>
                    ) : (
                      <span className="w-3.5 shrink-0" aria-hidden="true" />
                    )}
                    <button
                      type="button"
                      role="checkbox"
                      aria-checked={isChecked}
                      aria-disabled={disabled}
                      aria-label={`Chart ${item.label}`}
                      title={
                        disabled
                          ? `Up to ${MAX_SERIES} series; uncheck one first`
                          : undefined
                      }
                      data-testid="fin-check"
                      className={`relative inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-[2px] border p-0 ${
                        isChecked
                          ? 'border-transparent'
                          : 'border-line-strong bg-panel'
                      } ${disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer'}`}
                      style={
                        isChecked
                          ? {background: `var(--k-s${slot})`}
                          : undefined
                      }
                      onClick={() => {
                        if (!disabled) {
                          onToggleCheck(item.id);
                        }
                      }}
                    >
                      {isChecked && (
                        <span
                          className="h-1 w-[7px] -translate-y-px -rotate-45 border-b-2 border-l-2 border-white"
                          aria-hidden="true"
                        />
                      )}
                    </button>
                    <span
                      title={
                        item.rule === null ? undefined : `Derived: ${item.rule}`
                      }
                    >
                      {item.label}
                    </span>
                  </span>
                </th>
                {periods.map(p => {
                  const point = map.get(p.key);
                  if (point === undefined) {
                    return (
                      <td
                        key={p.key}
                        className="num border-b border-line px-2.5 py-1.5 text-right text-muted group-hover:bg-raised"
                      >
                        --
                      </td>
                    );
                  }
                  const source = sources[point.source];
                  const title =
                    `${p.key}: ${formatValue(point.value, item.unit)}.` +
                    (source === undefined
                      ? ''
                      : ` ${source.form} filed ${formatDate(source.filed)}`) +
                    (point.derived ? `. Derived: ${point.note ?? ''}` : '') +
                    (!point.derived && point.note !== null
                      ? `. ${point.note}`
                      : '');
                  return (
                    <td
                      key={p.key}
                      title={title}
                      data-derived={point.derived}
                      className={`num whitespace-nowrap border-b border-line px-2.5 py-1.5 text-right group-hover:bg-raised ${
                        point.derived ? 'fin-derived italic' : ''
                      }`}
                    >
                      {cellText(point.value, item.unit, scale, digits)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
