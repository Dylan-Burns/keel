/** The ticker checks of the companies page. */

/** A ticker as the API takes it: letters, digits, `.`, `-`, at most 10. */
export const TICKER = /^[A-Za-z0-9.-]{1,10}$/;

/**
 * Splits a field of tickers at commas and white space.
 *
 * @param text The field as typed.
 * @return The upper-case tickers.
 */
export function tickersOf(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .filter(Boolean)
    .map(t => t.toUpperCase());
}
