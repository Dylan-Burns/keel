/**
 * Recorded financials data for the Vitest tests and the Playwright route
 * mocks: a small NVIDIA statement set with the values of its 10-K for
 * fiscal 2025 and its 10-Q filings. The application code never imports
 * this module.
 */
import type {
  FinancialsCompanies,
  FinancialsItem,
  FinancialsPoint,
  FinancialsResponse,
} from '../api/types';

/** The companies of `GET /api/financials`. */
export const FIN_COMPANIES: FinancialsCompanies = {
  companies: [
    {ticker: 'AAPL', company: 'Apple Inc', cik: '0000320193'},
    {ticker: 'JPM', company: 'JPMorgan Chase & Co', cik: '0000019617'},
    {ticker: 'NVDA', company: 'NVIDIA Corporation', cik: '0001045810'},
  ],
};

const YEARS: readonly (readonly [string, string, string])[] = [
  ['FY2023', '2022-01-31', '2023-01-29'],
  ['FY2024', '2023-01-30', '2024-01-28'],
  ['FY2025', '2024-01-29', '2025-01-26'],
];

const QUARTERS: readonly (readonly [string, string, string])[] = [
  ['Q1 FY2025', '2024-01-29', '2024-04-28'],
  ['Q2 FY2025', '2024-04-29', '2024-07-28'],
  ['Q3 FY2025', '2024-07-29', '2024-10-27'],
  ['Q4 FY2025', '2024-10-28', '2025-01-26'],
];

function points(
  periods: readonly (readonly [string, string, string])[],
  values: readonly number[],
  instant = false,
): FinancialsPoint[] {
  return periods.map(([label, start, end], i) => {
    const q4 = label.startsWith('Q4');
    return {
      label,
      start: instant ? null : start,
      end,
      value: values[i] ?? 0,
      source: q4 || !label.startsWith('Q') ? 0 : 1,
      derived: q4,
      note: q4 ? 'fiscal year minus the nine-month year-to-date' : null,
    };
  });
}

function item(
  id: string,
  label: string,
  annual: readonly number[],
  quarterly: readonly number[],
  extra: Partial<FinancialsItem> = {},
): {readonly annual: FinancialsItem; readonly quarterly: FinancialsItem} {
  const base = {
    id,
    label,
    parent: null,
    unit: 'USD' as const,
    rule: null,
    ...extra,
  };
  const instant = extra.unit === undefined && id === 'total_assets';
  return {
    annual: {...base, points: points(YEARS, annual, instant)},
    quarterly: {...base, points: points(QUARTERS, quarterly, instant)},
  };
}

const B = 1e9;
const ROWS = {
  revenue: item(
    'revenue',
    'Total revenue',
    [26.974 * B, 60.922 * B, 130.497 * B],
    [26.044 * B, 30.04 * B, 35.082 * B, 39.331 * B],
  ),
  netIncome: item(
    'net_income',
    'Net income',
    [4.368 * B, 29.76 * B, 72.88 * B],
    [14.881 * B, 16.599 * B, 19.309 * B, 22.091 * B],
  ),
  opex: item(
    'opex',
    'Operating expenses',
    [11.132 * B, 11.329 * B, 16.405 * B],
    [3.497 * B, 3.932 * B, 4.287 * B, 4.689 * B],
  ),
  rnd: item(
    'rnd',
    'Research and development',
    [7.339 * B, 8.675 * B, 12.914 * B],
    [2.72 * B, 3.09 * B, 3.39 * B, 3.714 * B],
    {parent: 'opex'},
  ),
  eps: item(
    'eps_diluted',
    'Diluted EPS',
    [0.174, 1.19, 2.94],
    [0.6, 0.67, 0.78, 0.89],
    {unit: 'USD/shares'},
  ),
  assets: item(
    'total_assets',
    'Total assets',
    [41.182 * B, 65.728 * B, 111.601 * B],
    [77.072 * B, 85.227 * B, 96.013 * B, 111.601 * B],
  ),
  ocf: item(
    'ocf',
    'Operating cash flow',
    [5.641 * B, 28.09 * B, 64.089 * B],
    [15.345 * B, 14.489 * B, 17.629 * B, 16.629 * B],
  ),
};

function response(period: 'annual' | 'quarterly'): FinancialsResponse {
  const pick = (row: {
    readonly annual: FinancialsItem;
    readonly quarterly: FinancialsItem;
  }): FinancialsItem => row[period];
  return {
    ticker: 'NVDA',
    company: 'NVIDIA Corporation',
    cik: '0001045810',
    period,
    fetched_at: '2026-10-22T04:00:00Z',
    fiscal_year_end_month: 1,
    splits: [
      {date: '2021-08-20', ratio: 4},
      {date: '2024-08-28', ratio: 10},
    ],
    sources: [
      {
        form: '10-K',
        accession: '0001045810-25-000023',
        filed: '2025-02-26',
        url: 'https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/0001045810-25-000023-index.htm',
      },
      {
        form: '10-Q',
        accession: '0001045810-24-000316',
        filed: '2024-11-20',
        url: 'https://www.sec.gov/Archives/edgar/data/1045810/000104581024000316/0001045810-24-000316-index.htm',
      },
    ],
    statements: [
      {
        id: 'income',
        label: 'Income Statement',
        defaults: ['revenue', 'net_income'],
        items: [
          ROWS.revenue,
          ROWS.opex,
          ROWS.rnd,
          ROWS.netIncome,
          ROWS.eps,
        ].map(pick),
      },
      {
        id: 'balance',
        label: 'Balance Sheet',
        defaults: ['total_assets'],
        items: [pick(ROWS.assets)],
      },
      {
        id: 'cash',
        label: 'Cash Flow',
        defaults: ['ocf'],
        items: [pick(ROWS.ocf)],
      },
    ],
  };
}

/** NVIDIA's annual statements. */
export const FIN_NVDA_ANNUAL: FinancialsResponse = response('annual');

/** NVIDIA's quarterly statements, with a derived Q4. */
export const FIN_NVDA_QUARTERLY: FinancialsResponse = response('quarterly');
