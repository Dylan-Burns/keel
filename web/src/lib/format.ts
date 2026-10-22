/**
 * Formatters of the operations pages: times, sizes, and money.
 */

/**
 * Formats an ISO timestamp in the browser's time zone.
 *
 * @param timestamp The ISO 8601 time, or null.
 * @return The local date and time, the raw text when it does not parse, or
 *     a dash for null.
 */
export function when(timestamp: string | null | undefined): string {
  if (timestamp === null || timestamp === undefined || timestamp === '') {
    return '--';
  }
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? timestamp : parsed.toLocaleString();
}

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

/**
 * Formats a byte count with a binary unit.
 *
 * @param size The bytes.
 * @return The text, such as `1.2 MB`.
 */
export function bytes(size: number | null | undefined): string {
  if (size === null || size === undefined || !Number.isFinite(size)) {
    return '--';
  }
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${UNITS[unit]}`;
}

/**
 * Formats US dollars.
 *
 * @param amount The amount.
 * @param digits The decimals (2 by default).
 * @return The text, such as `$4.27`.
 */
export function usd(amount: number | null | undefined, digits = 2): string {
  return amount === null || amount === undefined || !Number.isFinite(amount)
    ? '--'
    : `$${amount.toFixed(digits)}`;
}

/**
 * Formats a scalar of a job result or parameters for display.
 *
 * @param value The JSON value.
 * @return The text.
 */
export function scalar(value: unknown): string {
  if (value === null || value === undefined) {
    return 'none';
  }
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.every(v => typeof v !== 'object' || v === null)
      ? value.map(scalar).join(', ')
      : `${value.length} items`;
  }
  return JSON.stringify(value);
}
