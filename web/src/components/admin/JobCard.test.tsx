import {act, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../../api/client';
import {job, routeFetch} from '../../testing/admin';
import {JobCard} from './JobCard';
import {POLL_MS} from './useJob';

const ID = '3f2a9c0d1e4b5a67';

beforeEach(() => {
  vi.useFakeTimers();
  window.sessionStorage.setItem(TOKEN_KEY, 'admin-token');
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function flush(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

describe('JobCard', () => {
  it('polls while the job runs and stops at its final status', async () => {
    const states = [
      job({status: 'queued'}),
      job({
        status: 'running',
        phase: 'building the index',
        progress: {done: 1, total: 4},
        log: ['fetching ZTS'],
      }),
      job({
        status: 'succeeded',
        phase: 'done',
        progress: {done: 4, total: 4},
        result: {ticker: 'ZTS', index_version: '1.1.0'},
        log: ['fetching ZTS', '10-K filed 2026-02-12'],
      }),
    ];
    let served = 0;
    const calls = routeFetch({
      [`GET /api/admin/jobs/${ID}`]: () => ({
        body: states[Math.min(served++, states.length - 1)],
      }),
    });
    const onFinal = vi.fn();
    render(<JobCard id={ID} initial={job()} onFinal={onFinal} />);
    await flush();
    expect(screen.getByTestId('job-card')).toHaveAttribute(
      'data-status',
      'queued',
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });
    expect(screen.getByTestId('job-phase')).toHaveTextContent(
      'building the index',
    );
    expect(screen.getByTestId('job-progress')).toHaveTextContent('1 of 4');
    expect(screen.getByRole('progressbar')).toHaveAttribute(
      'aria-valuenow',
      '25',
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });
    expect(screen.getByTestId('job-card')).toHaveAttribute(
      'data-status',
      'succeeded',
    );
    expect(screen.getByTestId('job-result')).toHaveTextContent('1.1.0');
    expect(screen.getByTestId('job-log')).toHaveTextContent(
      '10-K filed 2026-02-12',
    );
    expect(onFinal).toHaveBeenCalledOnce();
    const polls = calls.length;
    expect(polls).toBe(3);
    // No poll after the final status.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 10);
    });
    expect(calls).toHaveLength(polls);
    expect(onFinal).toHaveBeenCalledOnce();
  });

  it('stops polling when it unmounts', async () => {
    const calls = routeFetch({
      [`GET /api/admin/jobs/${ID}`]: {body: job({status: 'running'})},
    });
    const {unmount} = render(<JobCard id={ID} />);
    await flush();
    expect(calls).toHaveLength(1);
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 5);
    });
    expect(calls).toHaveLength(1);
  });

  it('shows the error of a failed job and stops', async () => {
    const calls = routeFetch({
      [`GET /api/admin/jobs/${ID}`]: {
        body: job({
          status: 'failed',
          phase: 'failed',
          error: 'EdgarFetchError: offline',
        }),
      },
    });
    render(<JobCard id={ID} />);
    await flush();
    expect(screen.getByTestId('job-error')).toHaveTextContent(
      'EdgarFetchError: offline',
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    });
    expect(calls).toHaveLength(1);
  });

  it('cancels a queued job', async () => {
    const calls = routeFetch({
      [`GET /api/admin/jobs/${ID}`]: {body: job({status: 'queued'})},
      [`POST /api/admin/jobs/${ID}/cancel`]: {
        body: job({status: 'cancelled', phase: 'cancelled'}),
      },
    });
    render(<JobCard id={ID} />);
    await flush();
    fireEvent.click(screen.getByTestId('job-cancel'));
    await flush();
    expect(calls.some(c => c.method === 'POST')).toBe(true);
    expect(screen.getByTestId('job-card')).toHaveAttribute(
      'data-status',
      'cancelled',
    );
  });

  it('stops on a 404', async () => {
    const calls = routeFetch({});
    render(<JobCard id={ID} />);
    await flush();
    expect(screen.getByRole('alert')).toHaveTextContent('No job with this ID.');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 4);
    });
    expect(calls).toHaveLength(1);
  });
});
