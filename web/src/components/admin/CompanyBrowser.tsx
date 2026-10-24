import type {JSX} from 'react';
import {useCallback, useEffect, useState} from 'react';

import {fetchDirectory, fetchIndustry, searchDirectory} from '../../api/admin';
import {ApiError} from '../../api/client';
import type {DirectoryCompany, DirectoryResponse} from '../../api/types';
import {BROWSER_COLUMNS, CompanyRow} from './CompanyRow';
import type {IndustryLoad} from './IndustryRows';
import {OpsPanelHead} from './OpsPanelHead';
import {SectorRows} from './SectorRows';
import {useCompanyAdder} from './useCompanyAdder';

/** The wait after the last key before the search goes out. */
export const SEARCH_DEBOUNCE_MS = 300;

/** The load state of the sectors. */
type Overview =
  | {readonly kind: 'loading'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly data: DirectoryResponse};

/** The state of a search. */
type Search =
  | {readonly kind: 'idle'}
  | {readonly kind: 'loading'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly items: readonly DirectoryCompany[]};

/**
 * The message of a failed request.
 *
 * @param error The error.
 * @param fallback The text when the server sent none.
 * @return The message.
 */
function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? `${error.message}.` : fallback;
}

/**
 * Flips 1 member of a set.
 *
 * @param set The set.
 * @param key The member.
 * @return A new set.
 */
function flipped(set: ReadonlySet<string>, key: string): Set<string> {
  const next = new Set(set);
  if (next.has(key)) {
    next.delete(key);
  } else {
    next.add(key);
  }
  return next;
}

/** Props of CompanyBrowser. */
export interface CompanyBrowserProps {
  /** Called when an add job ends, to reload the watch list. */
  readonly onDone: () => void;
}

/**
 * The company browser of the companies page (admin): a nested table of
 * sectors (the SEC offices), their industries (SIC codes), and the
 * companies of an industry with a ticker, each with an Add button that
 * starts `keel add`. Opening an industry loads its companies: the first
 * time from SEC EDGAR (1 request per 100 registrants), then from the
 * server cache. The search box finds a company by ticker or name.
 *
 * @param props Called when an add job ends.
 * @return The panel.
 */
export function CompanyBrowser({onDone}: CompanyBrowserProps): JSX.Element {
  const [overview, setOverview] = useState<Overview>({kind: 'loading'});
  const [openSectors, setOpenSectors] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [openIndustries, setOpenIndustries] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [loads, setLoads] = useState<Readonly<Record<string, IndustryLoad>>>(
    {},
  );
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState<Search>({kind: 'idle'});
  // Bumped when an add job ends, so open search results load again.
  const [searchRun, setSearchRun] = useState(0);
  const loadIndustry = useCallback((code: string): void => {
    setLoads(current => ({...current, [code]: {kind: 'loading'}}));
    fetchIndustry(code)
      .then(data =>
        setLoads(current => ({...current, [code]: {kind: 'ready', data}})),
      )
      .catch((error: unknown) =>
        setLoads(current => ({
          ...current,
          [code]: {
            kind: 'error',
            message: messageOf(error, 'The companies could not load.'),
          },
        })),
      );
  }, []);

  // When an add job ends, the open industries load again (their Indexed
  // marks change) and the closed ones load when they open.
  const reloadAll = useCallback((): void => {
    setLoads({});
    setSearchRun(n => n + 1);
    for (const code of openIndustries) {
      loadIndustry(code);
    }
    onDone();
  }, [loadIndustry, onDone, openIndustries]);
  const adder = useCompanyAdder(reloadAll);

  useEffect(() => {
    let cancelled = false;
    fetchDirectory()
      .then(data => {
        if (!cancelled) {
          setOverview({kind: 'ready', data});
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setOverview({
            kind: 'error',
            message: messageOf(error, 'The sectors could not load.'),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const text = query.trim();
  // A text of 0 or 1 characters shows the tree; the search state stays
  // as it was until the next search.
  const shown: Search = text.length < 2 ? {kind: 'idle'} : search;
  useEffect(() => {
    if (text.length < 2) {
      return undefined;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearch({kind: 'loading'});
      searchDirectory(text, controller.signal)
        .then(found => setSearch({kind: 'ready', items: found.items}))
        .catch((error: unknown) => {
          if (!controller.signal.aborted) {
            setSearch({
              kind: 'error',
              message: messageOf(error, 'The search failed.'),
            });
          }
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [text, searchRun]);

  const onToggleIndustry = (code: string): void => {
    const opening = !openIndustries.has(code);
    setOpenIndustries(flipped(openIndustries, code));
    const known = loads[code];
    if (opening && (known === undefined || known.kind === 'error')) {
      loadIndustry(code);
    }
  };

  return (
    <section
      className="panel"
      aria-label="Browse companies"
      data-testid="browse"
    >
      <OpsPanelHead title="Browse companies" note="SEC industries (SIC)" />
      <div className="panel-body space-y-3">
        <p className="text-[12.5px] text-ink-2">
          The SEC files every registrant under an industry code, and each code
          under the office that reviews it; the offices are the sectors here.
          Opening an industry asks SEC EDGAR for its 10-K filers once and keeps
          the list for the configured period. Add starts the same job as{' '}
          <code className="font-mono text-[11.5px]">keel add</code>.
        </p>
        <label className="flex min-w-0 flex-col gap-1">
          <span className="section-title">Find a company</span>
          <input
            className="input w-full max-w-sm"
            type="search"
            value={query}
            placeholder="Ticker or name, such as ZTS or Zoetis"
            maxLength={64}
            autoComplete="off"
            data-testid="browse-search"
            onChange={event => setQuery(event.target.value)}
          />
        </label>
        {overview.kind === 'loading' && (
          <p className="text-[12px] text-muted" role="status">
            Loading the sectors.
          </p>
        )}
        {overview.kind === 'error' && (
          <p className="text-[12px] text-down" role="alert">
            {overview.message}
          </p>
        )}
        <div className="overflow-x-auto border border-line">
          <table className="grid-table" data-testid="browse-table">
            <thead>
              <tr>
                <th scope="col">
                  {shown.kind === 'idle'
                    ? 'Sector / industry / company'
                    : 'Company'}
                </th>
                <th scope="col">Ticker</th>
                <th scope="col" className="hidden sm:table-cell">
                  CIK
                </th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.kind === 'loading' && (
                <tr>
                  <td colSpan={BROWSER_COLUMNS} className="font-normal">
                    <span className="text-muted" role="status">
                      Searching.
                    </span>
                  </td>
                </tr>
              )}
              {shown.kind === 'error' && (
                <tr>
                  <td colSpan={BROWSER_COLUMNS} className="font-normal">
                    <span className="text-down" role="alert">
                      {shown.message}
                    </span>
                  </td>
                </tr>
              )}
              {shown.kind === 'ready' && shown.items.length === 0 && (
                <tr data-testid="browse-no-match">
                  <td
                    colSpan={BROWSER_COLUMNS}
                    className="font-normal text-muted"
                  >
                    No company of the SEC ticker map matches.
                  </td>
                </tr>
              )}
              {shown.kind === 'ready' &&
                shown.items.map(company => (
                  <CompanyRow
                    key={company.cik}
                    company={company}
                    adder={adder}
                    depth={0}
                  />
                ))}
              {shown.kind === 'idle' &&
                overview.kind === 'ready' &&
                overview.data.sectors.map(sector => (
                  <SectorRows
                    key={sector.name}
                    sector={sector}
                    open={openSectors.has(sector.name)}
                    openIndustries={openIndustries}
                    loads={loads}
                    adder={adder}
                    onToggle={name =>
                      setOpenSectors(current => flipped(current, name))
                    }
                    onToggleIndustry={onToggleIndustry}
                    onRetry={loadIndustry}
                  />
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
