import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../../api/client';
import {FORBIDDEN, job, routeFetch, submitted} from '../../testing/admin';
import {CompaniesPage} from './CompaniesPage';

const WATCH = {
  items: [{ticker: 'ZTS', user: 'carol', added_date: '2026-10-22', mine: true}],
  tickers: ['ZTS'],
};

beforeEach(() => {
  window.sessionStorage.setItem(TOKEN_KEY, 'token');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('CompaniesPage', () => {
  it('shows an analyst the watch list and no admin controls', async () => {
    routeFetch({
      'GET /api/admin/jobs': FORBIDDEN,
      'GET /api/watch': {
        body: {...WATCH, items: [{...WATCH.items[0], user: null, mine: false}]},
      },
    });
    render(<CompaniesPage />);
    expect(await screen.findByTestId('watch-row')).toHaveTextContent(
      'another user',
    );
    expect(screen.queryByTestId('add-form')).toBeNull();
    expect(screen.queryByTestId('watch-form')).toBeNull();
    expect(screen.queryByTestId('watch-remove')).toBeNull();
    expect(screen.queryByTestId('refresh-run')).toBeNull();
  });

  it('adds a company as the add job and shows it to the end', async () => {
    const calls = routeFetch({
      'GET /api/admin/jobs': {body: {items: [], active: null}},
      'GET /api/watch': {body: WATCH},
      'POST /api/admin/jobs': {status: 202, body: submitted()},
      'GET /api/admin/jobs/3f2a9c0d1e4b5a67': {
        body: job({
          status: 'succeeded',
          phase: 'done',
          result: {
            ticker: 'ZTS',
            filings: [
              {
                form: '10-K',
                filing_date: '2026-02-12',
                file_name: 'ZTS_10K_2026-02-12_full.txt',
                chunks: 20,
                quarantine: null,
              },
            ],
          },
        }),
      },
    });
    render(<CompaniesPage />);
    fireEvent.change(await screen.findByTestId('add-ticker'), {
      target: {value: 'zts'},
    });
    fireEvent.click(screen.getByTestId('add-submit'));
    await waitFor(() =>
      expect(screen.getByTestId('job-card')).toHaveAttribute(
        'data-status',
        'succeeded',
      ),
    );
    expect(calls.find(c => c.method === 'POST')?.body).toEqual({
      kind: 'add',
      params: {ticker: 'ZTS'},
    });
    expect(screen.getByTestId('job-result-filings')).toHaveTextContent(
      'ZTS_10K_2026-02-12_full.txt',
    );
    // The watch list reloads when the job ends.
    await waitFor(() =>
      expect(calls.filter(c => c.path === '/api/watch')).toHaveLength(2),
    );
  });

  it('refuses a bad ticker before it sends anything', async () => {
    const calls = routeFetch({
      'GET /api/admin/jobs': {body: {items: [], active: null}},
      'GET /api/watch': {body: WATCH},
    });
    render(<CompaniesPage />);
    fireEvent.change(await screen.findByTestId('add-ticker'), {
      target: {value: 'BAD TICKER'},
    });
    fireEvent.click(screen.getByTestId('add-submit'));
    const panel = screen.getByRole('region', {name: 'Add a company'});
    expect(within(panel).getByRole('alert')).toHaveTextContent(
      '1 to 10 letters',
    );
    expect(calls.some(c => c.method === 'POST')).toBe(false);
  });

  it('shows the running job on a 409', async () => {
    routeFetch({
      'GET /api/admin/jobs': {body: {items: [], active: null}},
      'GET /api/watch': {body: WATCH},
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
    render(<CompaniesPage />);
    fireEvent.click(await screen.findByTestId('refresh-dry-run'));
    expect(await screen.findByTestId('job-busy-link')).toHaveAttribute(
      'href',
      '/jobs/3f2a9c0d1e4b5a67',
    );
  });

  it('runs the refresh dry run and the facts job', async () => {
    const calls = routeFetch({
      'GET /api/admin/jobs': {body: {items: [], active: null}},
      'GET /api/watch': {body: WATCH},
      ['POST /api/admin/jobs']: call => ({
        status: 202,
        body: submitted({kind: (call.body as {kind: 'refresh'}).kind}),
      }),
    });
    render(<CompaniesPage />);
    fireEvent.click(await screen.findByTestId('refresh-dry-run'));
    fireEvent.change(screen.getByTestId('facts-ticker'), {
      target: {value: 'nvda'},
    });
    fireEvent.click(screen.getByTestId('facts-submit'));
    await waitFor(() =>
      expect(calls.filter(c => c.method === 'POST').map(c => c.body)).toEqual([
        {kind: 'refresh', params: {dry_run: true}},
        {kind: 'facts', params: {ticker: 'NVDA'}},
      ]),
    );
  });

  it('lets an admin watch tickers and remove a row after a confirmation', async () => {
    const calls = routeFetch({
      'GET /api/admin/jobs': {body: {items: [], active: null}},
      'GET /api/watch': {body: WATCH},
      'POST /api/watch': {
        body: {user: 'carol', added: ['WDAY'], unchanged: ['ZTS']},
      },
      'DELETE /api/watch/ZTS': {status: 204},
    });
    render(<CompaniesPage />);
    fireEvent.change(await screen.findByTestId('watch-tickers'), {
      target: {value: 'wday, zts'},
    });
    fireEvent.click(screen.getByTestId('watch-add'));
    expect(await screen.findByTestId('watch-notice')).toHaveTextContent(
      'Watching WDAY. Already watched: ZTS.',
    );
    expect(
      calls.find(c => c.path === '/api/watch' && c.method === 'POST')?.body,
    ).toEqual({
      tickers: ['WDAY', 'ZTS'],
    });
    fireEvent.click(screen.getByTestId('watch-remove'));
    fireEvent.click(screen.getByTestId('watch-remove-confirm'));
    await waitFor(() =>
      expect(calls.some(c => c.method === 'DELETE')).toBe(true),
    );
    expect(calls.find(c => c.method === 'DELETE')?.path).toBe(
      '/api/watch/ZTS?user=carol',
    );
  });
});
