import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../../api/client';
import {LAST_TICKER_KEY} from '../../lib/financials';
import {
  FIN_COMPANIES,
  FIN_NVDA_ANNUAL,
  FIN_NVDA_QUARTERLY,
} from '../../testing/financials';
import {FinancialsPage} from './FinancialsPage';

const calls: string[] = [];

function serve(status = 200): void {
  calls.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) => {
      calls.push(path);
      const url = new URL(path, 'http://x');
      if (status !== 200) {
        return Promise.resolve(
          new Response(
            JSON.stringify({detail: {code: 'x', message: 'refused'}}),
            {status},
          ),
        );
      }
      const body =
        url.pathname === '/api/financials'
          ? FIN_COMPANIES
          : url.pathname === '/api/financials/NVDA'
            ? url.searchParams.get('period') === 'quarterly'
              ? FIN_NVDA_QUARTERLY
              : FIN_NVDA_ANNUAL
            : null;
      return Promise.resolve(
        body === null
          ? new Response(
              JSON.stringify({detail: {code: 'unknown_ticker', message: 'no'}}),
              {status: 404},
            )
          : new Response(JSON.stringify(body)),
      );
    }),
  );
}

beforeEach(() => {
  window.sessionStorage.setItem(TOKEN_KEY, 'token');
  window.history.replaceState(null, '', '/financials?ticker=NVDA');
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.history.replaceState(null, '', '/');
});

async function ready(): Promise<HTMLElement> {
  const page = screen.getByTestId('financials-page');
  await waitFor(() => expect(page).toHaveAttribute('data-load', 'ready'));
  return page;
}

describe('FinancialsPage', () => {
  it('opens the company of the link with its default series', async () => {
    serve();
    render(<FinancialsPage />);
    const page = await ready();
    expect(page).toHaveAttribute('data-ticker', 'NVDA');
    expect(screen.getByRole('heading', {level: 2})).toHaveTextContent(
      'NVIDIA CorporationNVDA',
    );
    expect(screen.getByTestId('fin-charts')).toHaveAttribute(
      'data-series',
      '2',
    );
    expect(screen.getByText(/fiscal year ends in January/)).toBeInTheDocument();
    expect(
      screen.getByText(/4-for-1 \(2021\) and 10-for-1 \(2024\)/),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem(LAST_TICKER_KEY)).toBe('NVDA');
    expect(screen.getByRole('combobox', {name: 'Company'})).toHaveValue('NVDA');
  });

  it('adds a series when a row is checked, and drops it again', async () => {
    serve();
    render(<FinancialsPage />);
    await ready();
    const row = document.querySelector<HTMLElement>('[data-row="opex"]')!;
    fireEvent.click(within(row).getByRole('checkbox'));
    expect(screen.getByTestId('fin-charts')).toHaveAttribute(
      'data-series',
      '3',
    );
    fireEvent.click(within(row).getByRole('checkbox'));
    expect(screen.getByTestId('fin-charts')).toHaveAttribute(
      'data-series',
      '2',
    );
  });

  it('switches to quarterly and between statements', async () => {
    serve();
    render(<FinancialsPage />);
    await ready();
    fireEvent.click(screen.getByRole('button', {name: 'Quarterly'}));
    await waitFor(() =>
      expect(screen.getByTestId('fin-table')).toHaveTextContent('Q4 FY2025'),
    );
    expect(calls).toContain('/api/financials/NVDA?period=quarterly');
    fireEvent.click(screen.getByRole('tab', {name: 'Balance Sheet'}));
    expect(screen.getByTestId('fin-legend')).toHaveTextContent('Total assets');
    // No parent rows: no Expand all.
    expect(screen.queryByRole('button', {name: 'Expand all'})).toBeNull();
    fireEvent.click(screen.getByRole('tab', {name: 'Income Statement'}));
    fireEvent.click(screen.getByRole('button', {name: 'Expand all'}));
    expect(document.querySelector('[data-row="rnd"]')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', {name: 'Collapse all'}));
    expect(document.querySelector('[data-row="rnd"]')).toBeNull();
  });

  it('opens the stored company when the link names none', async () => {
    serve();
    window.history.replaceState(null, '', '/financials');
    window.localStorage.setItem(LAST_TICKER_KEY, 'NVDA');
    render(<FinancialsPage />);
    await ready();
    expect(window.location.search).toBe('?ticker=NVDA');
  });

  it('opens the first indexed company without a link or a stored one', async () => {
    serve();
    window.history.replaceState(null, '', '/financials');
    render(<FinancialsPage />);
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        'AAPL is not in the index',
      ),
    );
    expect(calls).toContain('/api/financials/AAPL?period=annual');
  });

  it('asks for the token without one, and after a 401', async () => {
    window.sessionStorage.clear();
    serve();
    render(<FinancialsPage />);
    expect(screen.getByTestId('financials-page')).toHaveAttribute(
      'data-load',
      'no_token',
    );
    expect(calls).toHaveLength(0);
  });

  it('reports a refused token', async () => {
    serve(401);
    render(<FinancialsPage />);
    await waitFor(() =>
      expect(screen.getByTestId('financials-page')).toHaveAttribute(
        'data-load',
        'no_token',
      ),
    );
  });

  it('reports facts that are not available offline', async () => {
    serve(503);
    render(<FinancialsPage />);
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        /not available offline|could not load/,
      ),
    );
  });
});
