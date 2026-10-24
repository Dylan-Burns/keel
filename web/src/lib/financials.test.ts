import {afterEach, describe, expect, it, vi} from 'vitest';

import {FIN_NVDA_ANNUAL} from '../testing/financials';
import {
  LAST_TICKER_KEY,
  MAX_SERIES,
  SCALES,
  addSlot,
  autoScale,
  barPath,
  cellText,
  defaultChecks,
  defaultRange,
  formatDate,
  formatValue,
  monthName,
  niceTicks,
  perShare,
  perShareDigits,
  periodRange,
  periodsOf,
  readLastTicker,
  saveLastTicker,
  shortLabel,
  tableScale,
  tickText,
  treeRows,
} from './financials';
import {financialsPath, financialsTickerOf} from './links';

const income = FIN_NVDA_ANNUAL.statements[0]?.items ?? [];

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe('financials formats', () => {
  it('scales values and formats the tooltip value', () => {
    expect(autoScale(2e11)).toBe(SCALES.B);
    expect(autoScale(5e7)).toBe(SCALES.M);
    expect(autoScale(5e4)).toBe(SCALES.K);
    expect(autoScale(5)).toBe(SCALES['']);
    expect(formatValue(130_497e6, 'USD')).toBe('$130.5B');
    expect(formatValue(-2_677e6, 'USD')).toBe('-$2.68B');
    expect(formatValue(24_804e6, 'shares')).toBe('24.80B');
    expect(formatValue(2.46, 'USD/shares')).toBe('$2.46');
    expect(formatValue(null, 'USD')).toBe('--');
    expect(formatValue(42, 'USD')).toBe('$42');
  });

  it('formats per-share values with the decimals they need', () => {
    expect(perShare(0.1725)).toBe('$0.1725');
    expect(perShare(-1.5, 2)).toBe('-$1.50');
    expect(perShareDigits([0.17, 0.385])).toBe(3);
    expect(cellText(0.385, 'USD/shares', SCALES[''], 2)).toBe('$0.39');
    expect(cellText(130_497e6, 'USD', SCALES.M, 2)).toBe('130,497');
    expect(cellText(-5e6, 'USD', SCALES.M, 2)).toBe('-5.00');
    expect(cellText(-123, 'USD', SCALES[''], 2)).toBe('-123');
  });

  it('builds round axis ticks and their labels', () => {
    const ticks = niceTicks(0, 215e9, 5);
    expect(ticks).toEqual([0, 50e9, 100e9, 150e9, 200e9, 250e9]);
    expect(tickText(50e9, 'USD', SCALES.B, ticks)).toBe('$50B');
    expect(tickText(-50e9, 'USD', SCALES.B, ticks)).toBe('-$50B');
    expect(tickText(0, 'USD/shares', SCALES[''], [0, 0.5, 1])).toBe('$0');
    expect(tickText(0.5, 'USD/shares', SCALES[''], [0, 0.5, 1])).toBe('$0.50');
    expect(tickText(2e9, 'shares', SCALES.B, [0, 1e9, 2e9])).toBe('2B');
    expect(niceTicks(3, 3, 2)[0]).toBe(3);
  });

  it('formats dates, months, periods, and short labels', () => {
    expect(formatDate('2025-01-26')).toBe('Jan 26, 2025');
    expect(formatDate('soon')).toBe('soon');
    expect(monthName(1)).toBe('January');
    expect(monthName(null)).toBe('');
    expect(shortLabel('Q3 FY2025')).toBe("Q3 '25");
    expect(shortLabel('FY2025')).toBe('FY2025');
    const point = income[0]?.points[2];
    expect(point && periodRange(point)).toBe('Jan 29, 2024 to Jan 26, 2025');
    expect(periodRange({...point!, start: null})).toBe('as of Jan 26, 2025');
  });

  it('draws a bar up or down from the baseline', () => {
    expect(barPath(10, 100, 40, 20, 4)).toBe(
      'M10,100V44Q10,40 14,40H26Q30,40 30,44V100Z',
    );
    expect(barPath(10, 100, 160, 20, 4)).toBe(
      'M10,100V156Q10,160 14,160H26Q30,160 30,156V100Z',
    );
    expect(barPath(10, 100, 100.2, 20, 4)).toBe('');
  });
});

describe('financials periods and rows', () => {
  it('orders the periods of a statement by end', () => {
    expect(periodsOf(income).map(p => p.key)).toEqual([
      'FY2023',
      'FY2024',
      'FY2025',
    ]);
    expect(defaultRange(19, 'annual')).toEqual([13, 18]);
    expect(defaultRange(5, 'quarterly')).toEqual([0, 4]);
  });

  it('scales the table to millions for a large-cap statement', () => {
    const periods = periodsOf(income);
    expect(tableScale(income, periods, 'USD', 'auto')).toBe(SCALES.M);
    expect(tableScale(income, periods, 'USD', 'B')).toBe(SCALES.B);
    expect(tableScale(income, periods, 'shares', 'auto')).toBe(SCALES['']);
  });

  it('shows children only under an expanded parent', () => {
    const closed = treeRows(income, new Set());
    expect(closed.map(r => r.item.id)).not.toContain('rnd');
    expect(closed.find(r => r.item.id === 'opex')?.parent).toBe(true);
    const open = treeRows(income, new Set(['opex']));
    expect(open.find(r => r.item.id === 'rnd')?.depth).toBe(1);
  });

  it('gives each checked row the lowest free slot, 8 at most', () => {
    let checked = defaultChecks(['revenue', 'net_income']);
    expect([...checked.values()]).toEqual([1, 2]);
    const without = new Map(checked);
    without.delete('revenue');
    expect(addSlot(without, 'opex').get('opex')).toBe(1);
    for (let i = 0; i < MAX_SERIES; i += 1) {
      checked = addSlot(checked, `row${i}`);
    }
    expect(checked.size).toBe(MAX_SERIES);
    expect(addSlot(checked, 'one-more')).toBe(checked);
  });
});

describe('financials links and storage', () => {
  it('builds and reads the page link', () => {
    expect(financialsPath('NVDA')).toBe('/financials?ticker=NVDA');
    expect(financialsPath()).toBe('/financials');
    expect(financialsTickerOf('?ticker=brk.b')).toBe('BRK.B');
    expect(financialsTickerOf('?ticker=%3Cscript%3E')).toBeNull();
    expect(financialsTickerOf('')).toBeNull();
  });

  it('remembers the last ticker and survives a storage failure', () => {
    saveLastTicker('AAPL');
    expect(window.localStorage.getItem(LAST_TICKER_KEY)).toBe('AAPL');
    expect(readLastTicker()).toBe('AAPL');
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readLastTicker()).toBeNull();
    expect(() => saveLastTicker('JPM')).not.toThrow();
  });
});
