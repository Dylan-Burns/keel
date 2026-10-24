import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../../api/client';
import type {
  DirectoryCompany,
  DirectoryResponse,
  IndustryCompanies,
} from '../../api/types';
import type {Call} from '../../testing/admin';
import {job, routeFetch, submitted} from '../../testing/admin';
import {CompanyBrowser} from './CompanyBrowser';

/** A recorded reply of the stubbed fetch. */
interface Answer {
  readonly status?: number;
  readonly body?: unknown;
}

const DIRECTORY: DirectoryResponse = {
  industry_count: 3,
  sectors: [
    {
      name: 'Life Sciences',
      industries: [
        {
          code: '2834',
          title: 'PHARMACEUTICAL PREPARATIONS',
          office: 'Office of Life Sciences',
          companies: null,
        },
      ],
    },
    {
      name: 'Manufacturing',
      industries: [
        {
          code: '3674',
          title: 'SEMICONDUCTORS & RELATED DEVICES',
          office: 'Office of Manufacturing',
          companies: 3,
        },
        {
          code: '3672',
          title: 'PRINTED CIRCUIT BOARDS',
          office: 'Office of Manufacturing',
          companies: null,
        },
      ],
    },
  ],
};

function company(fields: Partial<DirectoryCompany>): DirectoryCompany {
  return {
    cik: '0001045810',
    ticker: 'NVDA',
    tickers: ['NVDA'],
    name: 'NVIDIA CORP',
    indexed: false,
    watched: false,
    addable: true,
    ...fields,
  };
}

const NVDA = company({indexed: true});
const AMD = company({
  cik: '0000002488',
  ticker: 'AMD',
  tickers: ['AMD'],
  name: 'ADVANCED MICRO DEVICES INC',
});
const INTC = company({
  cik: '0000050863',
  ticker: 'INTC',
  tickers: ['INTC'],
  name: 'INTEL CORP',
  watched: true,
});

const SEMIS: IndustryCompanies = {
  code: '3674',
  title: 'SEMICONDUCTORS & RELATED DEVICES',
  sector: 'Manufacturing',
  companies: [AMD, INTC, NVDA],
  registrants: 506,
  fetched_at: '2026-10-24T20:11:44Z',
  stale: false,
  truncated: false,
  sec_requests: 6,
};

beforeEach(() => {
  window.sessionStorage.setItem(TOKEN_KEY, 'token');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * Opens a sector, then 1 of its industries.
 *
 * @param sector The sector name.
 * @param code The SIC code.
 */
async function openIndustry(sector: string, code: string): Promise<void> {
  const sectorRow = await screen.findByText(sector);
  fireEvent.click(sectorRow.closest('button') as HTMLButtonElement);
  const row = screen
    .getAllByTestId('industry-row')
    .find(r => r.dataset['code'] === code) as HTMLElement;
  fireEvent.click(within(row).getByTestId('industry-toggle'));
}

describe('CompanyBrowser', () => {
  it('nests sectors, industries, and companies with their marks', async () => {
    const calls = routeFetch({
      'GET /api/admin/directory': {body: DIRECTORY},
      'GET /api/admin/directory/sic/3674': {body: SEMIS},
    });
    render(<CompanyBrowser onDone={() => undefined} />);
    const sectors = await screen.findAllByTestId('sector-row');
    expect(sectors.map(s => s.dataset['sector'])).toEqual([
      'Life Sciences',
      'Manufacturing',
    ]);
    // Closed sectors show no industry.
    expect(screen.queryByTestId('industry-row')).toBeNull();
    const toggle = within(sectors[1] as HTMLElement).getByTestId(
      'sector-toggle',
    );
    expect(toggle.tagName).toBe('BUTTON');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const industries = screen.getAllByTestId('industry-row');
    expect(industries.map(r => r.dataset['code'])).toEqual(['3674', '3672']);
    expect(industries[0]).toHaveTextContent('3 companies');
    expect(industries[1]).not.toHaveTextContent('compan');
    const industryToggle = within(industries[0] as HTMLElement).getByTestId(
      'industry-toggle',
    );
    fireEvent.click(industryToggle);
    expect(industryToggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('industry-loading')).toHaveTextContent(
      'SEC EDGAR',
    );
    const rows = await screen.findAllByTestId('company-row');
    expect(rows.map(r => r.dataset['ticker'])).toEqual(['AMD', 'INTC', 'NVDA']);
    expect(
      within(rows[2] as HTMLElement).getByTestId('badge-indexed'),
    ).toBeTruthy();
    expect(
      within(rows[1] as HTMLElement).getByTestId('badge-watched'),
    ).toBeTruthy();
    expect(
      within(rows[0] as HTMLElement).queryByTestId('badge-indexed'),
    ).toBeNull();
    expect(rows[0]).toHaveTextContent('0000002488');
    // An indexed company offers an update, the others an add.
    expect(
      within(rows[2] as HTMLElement).getByTestId('company-add'),
    ).toHaveTextContent('Update');
    // Closing and opening again reads the loaded list, no new request.
    fireEvent.click(industryToggle);
    expect(screen.queryByTestId('company-row')).toBeNull();
    fireEvent.click(industryToggle);
    expect(screen.getAllByTestId('company-row')).toHaveLength(3);
    expect(
      calls.filter(c => c.path === '/api/admin/directory/sic/3674'),
    ).toHaveLength(1);
  });

  it('shows the error of an industry and retries it', async () => {
    let tries = 0;
    const pharma = (): Answer => {
      tries += 1;
      return tries === 1
        ? {
            status: 502,
            body: {
              detail: {
                code: 'sec_unavailable',
                message: 'SEC EDGAR did not answer; try again later',
              },
            },
          }
        : {body: {...SEMIS, code: '2834', companies: []}};
    };
    routeFetch({
      'GET /api/admin/directory': {body: DIRECTORY},
      'GET /api/admin/directory/sic/2834': pharma,
    });
    render(<CompanyBrowser onDone={() => undefined} />);
    await openIndustry('Life Sciences', '2834');
    expect(await screen.findByTestId('industry-error')).toHaveTextContent(
      'SEC EDGAR did not answer',
    );
    fireEvent.click(screen.getByTestId('industry-retry'));
    expect(await screen.findByTestId('industry-empty')).toHaveTextContent(
      'No company',
    );
  });

  it('adds a company and turns the other Add buttons off until it ends', async () => {
    const done = vi.fn();
    const calls = routeFetch({
      'GET /api/admin/directory': {body: DIRECTORY},
      'GET /api/admin/directory/sic/3674': {body: SEMIS},
      'POST /api/admin/jobs': {
        status: 202,
        body: submitted({params: {ticker: 'AMD'}}),
      },
      'GET /api/admin/jobs/3f2a9c0d1e4b5a67': {
        body: job({
          params: {ticker: 'AMD'},
          status: 'succeeded',
          phase: 'done',
          result: {ticker: 'AMD', filings: []},
        }),
      },
    });
    render(<CompanyBrowser onDone={done} />);
    await openIndustry('Manufacturing', '3674');
    const rows = await screen.findAllByTestId('company-row');
    fireEvent.click(within(rows[0] as HTMLElement).getByTestId('company-add'));
    // While the job is sent and runs, no Add button takes a click.
    for (const button of screen.getAllByTestId('company-add')) {
      expect(button).toBeDisabled();
    }
    expect(calls.find(c => c.method === 'POST')?.body).toEqual({
      kind: 'add',
      params: {ticker: 'AMD'},
    });
    await waitFor(() =>
      expect(screen.getByTestId('job-card')).toHaveAttribute(
        'data-status',
        'succeeded',
      ),
    );
    // The job shows under the row it came from.
    expect(
      screen.getByTestId('company-job').previousElementSibling,
    ).toHaveAttribute('data-ticker', 'AMD');
    await waitFor(() => expect(done).toHaveBeenCalledTimes(1));
    // The open industry loads again for its new marks; Add is back on.
    await waitFor(() =>
      expect(
        calls.filter(c => c.path === '/api/admin/directory/sic/3674'),
      ).toHaveLength(2),
    );
    await waitFor(() => {
      for (const button of screen.getAllByTestId('company-add')) {
        expect(button).toBeEnabled();
      }
    });
  });

  it('shows another running job on a 409 in the row', async () => {
    routeFetch({
      'GET /api/admin/directory': {body: DIRECTORY},
      'GET /api/admin/directory/sic/3674': {body: SEMIS},
      'POST /api/admin/jobs': {
        status: 409,
        body: {
          detail: {
            code: 'job_running',
            message: 'the index job 3f2a9c0d1e4b5a67 is running',
            job_id: '3f2a9c0d1e4b5a67',
          },
        },
      },
    });
    render(<CompanyBrowser onDone={() => undefined} />);
    await openIndustry('Manufacturing', '3674');
    const rows = await screen.findAllByTestId('company-row');
    fireEvent.click(within(rows[1] as HTMLElement).getByTestId('company-add'));
    expect(await screen.findByTestId('job-busy-link')).toHaveAttribute(
      'href',
      '/jobs/3f2a9c0d1e4b5a67',
    );
    // The refused job leaves the buttons on.
    for (const button of screen.getAllByTestId('company-add')) {
      expect(button).toBeEnabled();
    }
  });

  it('turns off Add for a ticker keel add cannot take', async () => {
    routeFetch({
      'GET /api/admin/directory': {body: DIRECTORY},
      'GET /api/admin/directory/sic/3674': {
        body: {...SEMIS, companies: [company({ticker: 'X1', addable: false})]},
      },
    });
    render(<CompanyBrowser onDone={() => undefined} />);
    await openIndustry('Manufacturing', '3674');
    expect(await screen.findByTestId('company-add')).toBeDisabled();
  });

  it('searches by ticker or name after the typing stops', async () => {
    const found = (call: Call): Answer =>
      call.path.endsWith('q=zzz')
        ? {body: {items: []}}
        : {body: {items: [NVDA]}};
    const calls = routeFetch({
      'GET /api/admin/directory': {body: DIRECTORY},
      'GET /api/admin/directory/search': found,
    });
    render(<CompanyBrowser onDone={() => undefined} />);
    await screen.findAllByTestId('sector-row');
    const box = screen.getByTestId('browse-search');
    fireEvent.change(box, {target: {value: 'n'}});
    fireEvent.change(box, {target: {value: 'nv'}});
    fireEvent.change(box, {target: {value: 'nvidia'}});
    const row = await screen.findByTestId('company-row');
    expect(row).toHaveAttribute('data-ticker', 'NVDA');
    expect(screen.queryByTestId('sector-row')).toBeNull();
    // 1 request for the last text only, encoded.
    const searches = calls.filter(c =>
      c.path.startsWith('/api/admin/directory/search'),
    );
    expect(searches.map(c => c.path)).toEqual([
      '/api/admin/directory/search?q=nvidia',
    ]);
    fireEvent.change(box, {target: {value: 'zzz'}});
    expect(await screen.findByTestId('browse-no-match')).toBeTruthy();
    // 1 character shows the tree again.
    fireEvent.change(box, {target: {value: 'z'}});
    expect(screen.getAllByTestId('sector-row')).toHaveLength(2);
  });

  it('searches again when an add from the results ends', async () => {
    const calls = routeFetch({
      'GET /api/admin/directory': {body: DIRECTORY},
      'GET /api/admin/directory/search': {body: {items: [AMD]}},
      'POST /api/admin/jobs': {
        status: 202,
        body: submitted({params: {ticker: 'AMD'}}),
      },
      'GET /api/admin/jobs/3f2a9c0d1e4b5a67': {
        body: job({params: {ticker: 'AMD'}, status: 'succeeded'}),
      },
    });
    render(<CompanyBrowser onDone={() => undefined} />);
    await screen.findAllByTestId('sector-row');
    fireEvent.change(screen.getByTestId('browse-search'), {
      target: {value: 'amd'},
    });
    fireEvent.click(await screen.findByTestId('company-add'));
    await waitFor(() =>
      expect(
        calls.filter(c => c.path.startsWith('/api/admin/directory/search')),
      ).toHaveLength(2),
    );
  });

  it('shows the error when the sectors cannot load', async () => {
    routeFetch({
      'GET /api/admin/directory': {
        status: 503,
        body: {
          detail: {
            code: 'directory_unavailable',
            message: 'the SIC code list cannot be read',
          },
        },
      },
    });
    render(<CompanyBrowser onDone={() => undefined} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'the SIC code list cannot be read',
    );
  });
});
