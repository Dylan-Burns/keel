import type {JSX} from 'react';
import {useEffect, useMemo, useState} from 'react';

import {
  ApiError,
  fetchFinancials,
  fetchFinancialsCompanies,
  getToken,
  setToken,
} from '../../api/client';
import type {
  FinancialsCompany,
  FinancialsPeriod,
  FinancialsResponse,
} from '../../api/types';
import type {UnitChoice} from '../../lib/financials';
import {
  addSlot,
  defaultChecks,
  defaultRange,
  formatDate,
  monthName,
  periodsOf,
  readLastTicker,
  saveLastTicker,
  tableScale,
} from '../../lib/financials';
import {financialsPath, financialsTickerOf} from '../../lib/links';
import {PageBar} from '../PageBar';
import {TokenField} from '../TokenField';
import {CompanyPicker} from './CompanyPicker';
import {LineItemTable} from './LineItemTable';
import {PeriodToggle} from './PeriodToggle';
import {RangeSlider} from './RangeSlider';
import {StatementCharts} from './StatementCharts';
import {StatementTabs} from './StatementTabs';
import {UnitToggle} from './UnitToggle';

/** The load state of the page. */
type Load =
  | {readonly kind: 'no_token'}
  | {readonly kind: 'loading'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly data: FinancialsResponse};

/**
 * The message of a failed load.
 *
 * @param error The error.
 * @param ticker The ticker asked for.
 * @return The text for the page.
 */
function failure(error: unknown, ticker: string): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return `${ticker} is not in the index. Pick an indexed company.`;
    }
    if (error.status === 503) {
      return `The SEC company facts of ${ticker} are not available offline.`;
    }
  }
  return `The financials of ${ticker} could not load.`;
}

/**
 * The financials page at `/financials?ticker=NVDA`: the income statement,
 * the balance sheet, and the cash flow of an indexed company, as reported
 * in its 10-K and 10-Q XBRL. Annual or quarterly; a table of line items
 * whose checked rows become bar series (1 chart per unit); a range slider
 * over the periods; and a tooltip per period that names the filing of each
 * value and links to it on sec.gov. Without a ticker in the link, the page
 * opens the last company it showed, else the first indexed one.
 *
 * @return The page.
 */
export function FinancialsPage(): JSX.Element {
  const [tokenCount, setTokenCount] = useState(0);
  const [companies, setCompanies] = useState<FinancialsCompany[]>([]);
  const [ticker, setTicker] = useState<string | null>(() =>
    financialsTickerOf(window.location.search),
  );
  const [period, setPeriod] = useState<FinancialsPeriod>('annual');
  const [statementId, setStatementId] = useState('income');
  const [unit, setUnit] = useState<UnitChoice>('auto');
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [checked, setChecked] = useState<ReadonlyMap<string, number> | null>(
    null,
  );
  const [ranges, setRanges] = useState<
    Readonly<Record<string, readonly [number, number]>>
  >({});
  const [data, setData] = useState<FinancialsResponse | null>(null);
  const [load, setLoad] = useState<Load>(() =>
    getToken() === null ? {kind: 'no_token'} : {kind: 'loading'},
  );

  // The picker list; it also names the first company when the link has
  // none and nothing is stored.
  useEffect(() => {
    if (getToken() === null) {
      return;
    }
    let cancelled = false;
    fetchFinancialsCompanies()
      .then(body => {
        if (cancelled) {
          return;
        }
        setCompanies(body.companies);
        setTicker(current => {
          if (current !== null) {
            return current;
          }
          const stored = readLastTicker();
          const known = body.companies.find(c => c.ticker === stored);
          return known?.ticker ?? body.companies[0]?.ticker ?? null;
        });
        if (body.companies.length === 0) {
          setLoad({kind: 'error', message: 'No company is indexed yet.'});
        }
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          setLoad({kind: 'no_token'});
        } else {
          setLoad({kind: 'error', message: 'The companies could not load.'});
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tokenCount]);

  // The statements of the company and the period.
  useEffect(() => {
    if (ticker === null || getToken() === null) {
      return;
    }
    const controller = new AbortController();
    fetchFinancials(ticker, period, controller.signal)
      .then(data => {
        setData(data);
        setLoad({kind: 'ready', data});
        saveLastTicker(data.ticker);
        const wanted = financialsPath(data.ticker);
        if (`${window.location.pathname}${window.location.search}` !== wanted) {
          window.history.replaceState(null, '', wanted);
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setData(null);
        if (error instanceof ApiError && error.status === 401) {
          setLoad({kind: 'no_token'});
        } else {
          setLoad({kind: 'error', message: failure(error, ticker)});
        }
      });
    return () => controller.abort();
  }, [ticker, period, tokenCount]);

  const statement =
    data?.statements.find(s => s.id === statementId) ??
    data?.statements[0] ??
    null;
  const items = useMemo(() => statement?.items ?? [], [statement]);
  const all = useMemo(() => periodsOf(items), [items]);
  const rangeKey = `${statement?.id ?? ''}:${period}`;
  const [low, high] = ranges[rangeKey] ?? defaultRange(all.length, period);
  const shown = all.slice(low, high + 1);
  const ids = new Set(items.map(i => i.id));
  const checks = new Map(
    [...(checked ?? defaultChecks(statement?.defaults ?? []))].filter(([id]) =>
      ids.has(id),
    ),
  );
  const parents = items
    .filter(i => items.some(child => child.parent === i.id))
    .map(i => i.id);
  const allOpen = parents.length > 0 && parents.every(p => expanded.has(p));
  const usdScale = tableScale(items, shown, 'USD', unit);
  const sharesScale = tableScale(items, shown, 'shares', unit);
  const hasShares = items.some(i => i.unit === 'shares');
  const hasPerShare = items.some(i => i.unit === 'USD/shares');

  const pickTicker = (next: string): void => {
    // The old company's statements never show under the new name.
    setData(null);
    setLoad({kind: 'loading'});
    setTicker(next);
    setRanges({});
  };
  const pickPeriod = (next: FinancialsPeriod): void => {
    if (next !== period) {
      setLoad({kind: 'loading'});
      setPeriod(next);
    }
  };
  const pickStatement = (id: string): void => {
    setStatementId(id);
    setChecked(null);
  };
  const toggleCheck = (id: string): void => {
    if (checks.has(id)) {
      const next = new Map(checks);
      next.delete(id);
      setChecked(next);
    } else {
      setChecked(addSlot(checks, id));
    }
  };
  const toggleExpand = (id: string): void => {
    const next = new Set(expanded);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setExpanded(next);
  };
  const onSave = (token: string): void => {
    setToken(token);
    setLoad({kind: 'loading'});
    setTokenCount(n => n + 1);
  };

  const fiscal = monthName(data?.fiscal_year_end_month ?? null);
  const splits = data?.splits ?? [];
  return (
    <div
      className="min-h-screen bg-canvas font-sans text-ink"
      data-testid="financials-page"
      data-load={load.kind}
      data-period={period}
      data-ticker={data?.ticker ?? ''}
    >
      <PageBar title="Financials">
        <TokenField
          hasToken={load.kind !== 'no_token'}
          rejected={load.kind === 'no_token' && getToken() !== null}
          onSave={onSave}
        />
      </PageBar>
      <main className="mx-auto grid w-full max-w-[1280px] gap-3 px-2 py-3 sm:px-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {data !== null && (
            <h2 className="flex flex-wrap items-baseline gap-x-2.5 text-[18px] font-bold">
              {data.company}
              <span className="num text-[14px] font-bold text-accent">
                {data.ticker}
              </span>
            </h2>
          )}
          {companies.length > 0 && (
            <div className="sm:ml-auto">
              <CompanyPicker
                companies={companies}
                ticker={ticker}
                onChange={pickTicker}
              />
            </div>
          )}
          {data !== null && (
            <p className="w-full text-[11px] text-muted">
              {`CIK ${Number(data.cik)} · SEC XBRL company facts fetched ${formatDate(
                data.fetched_at.slice(0, 10),
              )} · values as reported, latest filing wins`}
            </p>
          )}
        </div>
        {load.kind === 'no_token' && (
          <p className="text-[13px] text-muted">
            Enter your access token to read the financials.
          </p>
        )}
        {load.kind === 'loading' && data === null && (
          <p className="text-[13px] text-muted" data-testid="fin-loading">
            Loading the financials.
          </p>
        )}
        {load.kind === 'error' && (
          <p className="notice notice-down text-[13px]" role="alert">
            {load.message}
          </p>
        )}
        {data !== null && statement !== null && load.kind !== 'no_token' && (
          <section className="panel" aria-label="Financials">
            <div className="panel-head">
              <h3 className="panel-title">Financials</h3>
              <p className="text-[11px] text-muted">
                {`${data.company} (${data.ticker}) · as reported in 10-K and 10-Q XBRL${
                  fiscal === '' ? '' : ` · fiscal year ends in ${fiscal}`
                }`}
              </p>
            </div>
            <StatementTabs
              tabs={data.statements.map(s => ({id: s.id, label: s.label}))}
              selected={statement.id}
              onSelect={pickStatement}
            />
            <div className="panel-head">
              <PeriodToggle period={period} onChange={pickPeriod} />
              <span className="section-title">Units</span>
              <UnitToggle unit={unit} onChange={setUnit} />
              {parents.length > 0 && (
                <button
                  type="button"
                  className="btn"
                  data-testid="fin-expand-all"
                  onClick={() =>
                    setExpanded(allOpen ? new Set() : new Set(parents))
                  }
                >
                  {allOpen ? 'Collapse all' : 'Expand all'}
                </button>
              )}
              <span className="text-[11px] text-muted sm:ml-auto">
                {`USD in ${usdScale.name || 'units'}${
                  hasShares ? `, shares in ${sharesScale.name || 'units'}` : ''
                }${hasPerShare ? ', per share in USD' : ''}`}
              </span>
            </div>
            <div className="panel-body">
              {shown.length === 0 ? (
                <p className="py-10 text-center text-[11px] text-muted">
                  The filings report no {period} values for this statement.
                </p>
              ) : (
                <StatementCharts
                  items={items}
                  checked={checks}
                  periods={shown}
                  unit={unit}
                  sources={data.sources}
                />
              )}
            </div>
            {all.length > 1 && (
              <RangeSlider
                count={all.length}
                low={low}
                high={high}
                labelOf={i => all[i]?.key ?? ''}
                onChange={(a, b) =>
                  setRanges(current => ({...current, [rangeKey]: [a, b]}))
                }
              />
            )}
            <LineItemTable
              items={items}
              periods={shown}
              checked={checks}
              expanded={expanded}
              usdScale={usdScale}
              sharesScale={sharesScale}
              sources={data.sources}
              onToggleCheck={toggleCheck}
              onToggleExpand={toggleExpand}
            />
            <p className="px-2.5 py-2 text-[11px] text-muted">
              <b className="text-ink-2">*</b> Derived, not filed as a single
              value: Q4 is the fiscal year minus the nine-month year-to-date;
              10-Q cash flows are year-to-date and are de-accumulated; free cash
              flow is operating cash flow minus capital expenditures. Faded bars
              are derived values.
              {splits.length > 0 &&
                ` Per-share values are adjusted for the ${splits
                  .map(
                    s =>
                      `${s.ratio >= 1 ? `${s.ratio}-for-1` : `1-for-${Math.round(1 / s.ratio)}`} (${s.date.slice(0, 4)})`,
                  )
                  .join(
                    ' and ',
                  )} stock ${splits.length === 1 ? 'split' : 'splits'}.`}{' '}
              Hover a period for its source filing; click to pin. Up to 8
              series. No analyst estimates: the SEC data holds reported values
              only.
            </p>
          </section>
        )}
      </main>
    </div>
  );
}
