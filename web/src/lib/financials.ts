/**
 * Pure helpers of the financials page: the periods of a statement, the
 * number formats of the table and the chart axes, the nice axis ticks, the
 * bar shape, the series slots, and the last viewed ticker.
 */
import type {
  FinancialsItem,
  FinancialsPeriod,
  FinancialsPoint,
  FinancialsUnit,
} from '../api/types';

/** The most series the chart draws at once (the palette has 8 colors). */
export const MAX_SERIES = 8;

/** The local storage key of the last company the page showed. */
export const LAST_TICKER_KEY = 'keel.financials.ticker';

/** A unit choice of the page: automatic, thousands, millions, billions. */
export type UnitChoice = 'auto' | 'K' | 'M' | 'B';

/** A divisor of the displayed numbers. */
export interface Scale {
  readonly div: number;
  readonly suffix: string;
  /** The name for the note: `millions`; empty for units. */
  readonly name: string;
}

/** The scales by key; `''` is no scaling. */
export const SCALES: Readonly<Record<'' | 'K' | 'M' | 'B', Scale>> = {
  '': {div: 1, suffix: '', name: ''},
  K: {div: 1e3, suffix: 'K', name: 'thousands'},
  M: {div: 1e6, suffix: 'M', name: 'millions'},
  B: {div: 1e9, suffix: 'B', name: 'billions'},
};

/**
 * The scale that keeps a magnitude readable.
 *
 * @param maxAbs The largest absolute value.
 * @return The scale.
 */
export function autoScale(maxAbs: number): Scale {
  if (maxAbs >= 1e10) {
    return SCALES.B;
  }
  if (maxAbs >= 1e7) {
    return SCALES.M;
  }
  if (maxAbs >= 1e4) {
    return SCALES.K;
  }
  return SCALES[''];
}

/**
 * Formats a number with fixed decimals and thousands separators.
 *
 * @param value The number.
 * @param digits The decimals.
 * @return The text.
 */
export function formatNumber(value: number, digits: number): string {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/**
 * The decimals (2 to 4) that show every value exactly.
 *
 * @param values The per-share values.
 * @return The decimal count.
 */
export function perShareDigits(values: readonly number[]): number {
  let digits = 2;
  for (const value of values) {
    while (
      digits < 4 &&
      Math.abs(value * 10 ** digits - Math.round(value * 10 ** digits)) > 1e-6
    ) {
      digits += 1;
    }
  }
  return digits;
}

/**
 * Formats a per-share value in dollars.
 *
 * @param value The value.
 * @param digits Fixed decimals, or null for the value's own (2 to 4).
 * @return `$2.46` or `-$0.12`.
 */
export function perShare(value: number, digits: number | null = null): string {
  const shown = digits ?? perShareDigits([value]);
  return `${value < 0 ? '-$' : '$'}${formatNumber(Math.abs(value), shown)}`;
}

/**
 * Formats 1 value with its own scale, for the tooltip.
 *
 * @param value The value, or null.
 * @param unit The unit.
 * @return `$130.50B`, `$2.46`, `24.6B` (shares), or `--`.
 */
export function formatValue(
  value: number | null,
  unit: FinancialsUnit,
): string {
  if (value === null) {
    return '--';
  }
  if (unit === 'USD/shares') {
    return perShare(value);
  }
  const scale = autoScale(Math.abs(value) * 10);
  const scaled = Math.abs(value) / scale.div;
  const digits = scale.div === 1 ? 0 : scaled >= 100 ? 1 : 2;
  const body = `${formatNumber(scaled, digits)}${scale.suffix}`;
  if (unit === 'shares') {
    return `${value < 0 ? '-' : ''}${body}`;
  }
  return `${value < 0 ? '-$' : '$'}${body}`;
}

/**
 * Formats an axis tick; all ticks of an axis share 1 decimal count.
 *
 * @param value The tick value.
 * @param unit The unit of the axis.
 * @param scale The scale of the axis.
 * @param all Every tick of the axis.
 * @return The label, such as `$50B` or `$1.50`.
 */
export function tickText(
  value: number,
  unit: FinancialsUnit,
  scale: Scale,
  all: readonly number[],
): string {
  const base = unit === 'USD/shares' ? 1 : 1 / scale.div;
  let digits = 0;
  for (const tick of all) {
    while (
      digits < 3 &&
      Math.abs(
        tick * base * 10 ** digits - Math.round(tick * base * 10 ** digits),
      ) > 1e-6
    ) {
      digits += 1;
    }
  }
  const sign = value < 0 ? '-' : '';
  if (unit === 'USD/shares') {
    if (value === 0) {
      return '$0';
    }
    const small = all.some(t => t !== 0 && Math.abs(t) < 1);
    return `${sign}$${formatNumber(Math.abs(value), Math.max(digits, small ? 2 : digits))}`;
  }
  const scaled = Math.abs(value) / scale.div;
  const dollar = unit === 'USD' ? '$' : '';
  return `${sign}${dollar}${formatNumber(scaled, digits)}${scale.suffix}`;
}

/**
 * Nice round axis ticks that cover a range.
 *
 * @param low The lowest value.
 * @param high The highest value.
 * @param count The wanted number of intervals.
 * @return The ticks, low to high, a multiple of 1, 2, or 5 apart.
 */
export function niceTicks(low: number, high: number, count: number): number[] {
  const top = low === high ? low + 1 : high;
  const step0 = (top - low) / Math.max(1, count);
  const magnitude = 10 ** Math.floor(Math.log10(step0));
  const error = step0 / magnitude;
  const step =
    (error >= 7.5 ? 10 : error >= 3.5 ? 5 : error >= 1.5 ? 2 : 1) * magnitude;
  const first = Math.floor(low / step) * step;
  const last = Math.ceil(top / step) * step;
  const out: number[] = [];
  for (let v = first; v <= last + step / 2; v += step) {
    out.push(Number(v.toPrecision(12)));
  }
  return out;
}

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

/**
 * Formats an ISO date as `Jan 26, 2025`.
 *
 * @param iso The date, `YYYY-MM-DD`.
 * @return The text, or the input when it does not parse.
 */
export function formatDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (match === null) {
    return iso;
  }
  return `${MONTHS[Number(match[2]) - 1]} ${Number(match[3])}, ${match[1]}`;
}

/**
 * The full name of a month.
 *
 * @param month The month, 1 to 12.
 * @return `January`, or an empty text.
 */
export function monthName(month: number | null): string {
  return month === null ? '' : (MONTH_NAMES[month - 1] ?? '');
}

/**
 * The period of a point: `Jan 29, 2024 to Jan 26, 2025` or `as of ...`.
 *
 * @param point The point.
 * @return The text.
 */
export function periodRange(point: FinancialsPoint): string {
  return point.start === null
    ? `as of ${formatDate(point.end)}`
    : `${formatDate(point.start)} to ${formatDate(point.end)}`;
}

/**
 * The short axis label of a period: `Q3 FY2025` becomes `Q3 '25`.
 *
 * @param label The period label.
 * @return The short label.
 */
export function shortLabel(label: string): string {
  const match = /^Q(\d) FY(\d{4})$/.exec(label);
  return match === null
    ? label
    : `Q${match[1] ?? ''} '${(match[2] ?? '').slice(2)}`;
}

/** 1 column of the statement: a fiscal period. */
export interface PeriodColumn {
  /** The period label, such as `FY2025`. */
  readonly key: string;
  /** The period end, for the order. */
  readonly end: string;
}

/**
 * The periods of a statement, oldest first.
 *
 * @param items The rows.
 * @return The distinct periods of their points.
 */
export function periodsOf(items: readonly FinancialsItem[]): PeriodColumn[] {
  const seen = new Map<string, PeriodColumn>();
  for (const item of items) {
    for (const point of item.points) {
      if (!seen.has(point.label)) {
        seen.set(point.label, {key: point.label, end: point.end});
      }
    }
  }
  return [...seen.values()].sort((a, b) =>
    a.end < b.end ? -1 : a.end > b.end ? 1 : 0,
  );
}

/**
 * The points of a row by period label.
 *
 * @param item The row.
 * @return The map.
 */
export function pointsByLabel(
  item: FinancialsItem,
): Map<string, FinancialsPoint> {
  return new Map(item.points.map(point => [point.label, point]));
}

/**
 * The default range of periods: the last 6 years or the last 8 quarters.
 *
 * @param count The number of periods.
 * @param period The period kind.
 * @return The first and last index.
 */
export function defaultRange(
  count: number,
  period: FinancialsPeriod,
): [number, number] {
  const span = period === 'annual' ? 6 : 8;
  return [Math.max(0, count - span), Math.max(0, count - 1)];
}

/**
 * The scale of a unit's table cells: millions for a large-cap statement.
 *
 * @param items The rows.
 * @param periods The shown periods.
 * @param unit `USD` or `shares`.
 * @param choice The unit choice of the page.
 * @return The scale.
 */
export function tableScale(
  items: readonly FinancialsItem[],
  periods: readonly PeriodColumn[],
  unit: FinancialsUnit,
  choice: UnitChoice,
): Scale {
  if (choice !== 'auto') {
    return SCALES[choice];
  }
  const keys = new Set(periods.map(p => p.key));
  let max = 0;
  for (const item of items) {
    if (item.unit !== unit) {
      continue;
    }
    for (const point of item.points) {
      if (keys.has(point.label)) {
        max = Math.max(max, Math.abs(point.value));
      }
    }
  }
  return max >= 1e9 ? SCALES.M : autoScale(max);
}

/**
 * Formats a table cell.
 *
 * @param value The value.
 * @param unit The unit of the row.
 * @param scale The scale of the unit's cells.
 * @param digits The decimals of a per-share row.
 * @return The text, such as `130,497` or `$2.94`.
 */
export function cellText(
  value: number,
  unit: FinancialsUnit,
  scale: Scale,
  digits: number,
): string {
  if (unit === 'USD/shares') {
    return perShare(value, digits);
  }
  const scaled = value / scale.div;
  const decimals = scale.div === 1 ? 0 : Math.abs(scaled) < 10 ? 2 : 0;
  return `${value < 0 ? '-' : ''}${formatNumber(Math.abs(scaled), decimals)}`;
}

/**
 * The SVG path of a bar with rounded data end, square on the baseline.
 *
 * @param x The left edge.
 * @param y0 The baseline.
 * @param y1 The data end.
 * @param width The bar width.
 * @param radius The corner radius.
 * @return The path, or an empty text for a bar under half a pixel.
 */
export function barPath(
  x: number,
  y0: number,
  y1: number,
  width: number,
  radius: number,
): string {
  const height = Math.abs(y1 - y0);
  if (height < 0.5) {
    return '';
  }
  const r = Math.min(radius, width / 2, height);
  const dir = y1 < y0 ? 1 : -1;
  return (
    `M${x},${y0}V${y1 + dir * r}Q${x},${y1} ${x + r},${y1}` +
    `H${x + width - r}Q${x + width},${y1} ${x + width},${y1 + dir * r}V${y0}Z`
  );
}

/**
 * Checks a row: gives it the lowest free color slot.
 *
 * @param checked The checked rows and their slots (1 to 8).
 * @param id The row to check.
 * @return The new map, or the same map when all slots are taken.
 */
export function addSlot(
  checked: ReadonlyMap<string, number>,
  id: string,
): ReadonlyMap<string, number> {
  const used = new Set(checked.values());
  for (let slot = 1; slot <= MAX_SERIES; slot += 1) {
    if (!used.has(slot)) {
      return new Map([...checked, [id, slot]]);
    }
  }
  return checked;
}

/**
 * The checked rows that open a statement: its defaults, in slot order.
 *
 * @param defaults The default rows.
 * @return The map of row to slot.
 */
export function defaultChecks(
  defaults: readonly string[],
): ReadonlyMap<string, number> {
  let checked: ReadonlyMap<string, number> = new Map();
  for (const id of defaults) {
    checked = addSlot(checked, id);
  }
  return checked;
}

/** 1 shown row of the tree: the item and its depth. */
export interface TreeRow {
  readonly item: FinancialsItem;
  readonly depth: number;
  /** True when the row has children. */
  readonly parent: boolean;
}

/**
 * The rows the table shows: top rows, and children of expanded rows.
 *
 * @param items The rows in statement order.
 * @param expanded The expanded rows.
 * @return The shown rows with their depth.
 */
export function treeRows(
  items: readonly FinancialsItem[],
  expanded: ReadonlySet<string>,
): TreeRow[] {
  const byId = new Map(items.map(item => [item.id, item]));
  const parents = new Set(
    items.map(item => item.parent).filter(id => id !== null),
  );
  const out: TreeRow[] = [];
  for (const item of items) {
    let depth = 0;
    let shown = true;
    let parent = item.parent;
    while (parent !== null) {
      depth += 1;
      if (!expanded.has(parent)) {
        shown = false;
      }
      parent = byId.get(parent)?.parent ?? null;
    }
    if (shown) {
      out.push({item, depth, parent: parents.has(item.id)});
    }
  }
  return out;
}

/**
 * Reads the last company the page showed.
 *
 * @return The ticker, or null when none is stored or storage fails.
 */
export function readLastTicker(): string | null {
  try {
    return window.localStorage.getItem(LAST_TICKER_KEY);
  } catch {
    return null;
  }
}

/**
 * Stores the company the page shows, for the next visit.
 *
 * @param ticker The ticker.
 */
export function saveLastTicker(ticker: string): void {
  try {
    window.localStorage.setItem(LAST_TICKER_KEY, ticker);
  } catch {
    // Storage off (a private window): the page still works.
  }
}
