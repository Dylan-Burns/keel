import {act, fireEvent, render, screen, within} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import type {JobStep} from '../../api/types';
import {TOKEN_KEY} from '../../api/client';
import {job, jobStep, routeFetch} from '../../testing/admin';
import {JobCard} from './JobCard';
import {JobSteps, TICK_MS} from './JobSteps';
import {POLL_MS} from './useJob';

const ID = '3f2a9c0d1e4b5a67';
const T0 = '2026-10-23T10:00:00+00:00';

function rows(): HTMLElement[] {
  return screen.getAllByTestId('job-step');
}

function row(key: string): HTMLElement {
  const found = rows().find(r => r.getAttribute('data-key') === key);
  if (found === undefined) {
    throw new Error(`no step ${key}`);
  }
  return found;
}

/** The steps of an add job: 2 done, embed running, 1 pending. */
function running(): JobStep[] {
  return [
    jobStep({
      key: 'resolve',
      name: 'Resolve the ticker',
      status: 'succeeded',
      started_at: T0,
      finished_at: '2026-10-23T10:00:02+00:00',
      log: ['ZTS is CIK 0001555280'],
    }),
    jobStep({
      key: 'download_10q',
      name: 'Download the 10-Q',
      status: 'skipped',
      log: ['skipped: no 10-Q picked'],
    }),
    jobStep({
      key: 'embed',
      name: 'Embed',
      status: 'running',
      started_at: T0,
      progress: {done: 1240, total: 3400, unit: 'chunks'},
      log: ['shard 1/2 ZTS_10K: 20 chunks embedded'],
    }),
    jobStep({key: 'reload', name: 'Reload the server'}),
  ];
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-23T10:01:05+00:00'));
  window.sessionStorage.setItem(TOKEN_KEY, 'admin-token');
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('JobSteps', () => {
  it('renders each step with its mark, name, duration, and counts', () => {
    render(<JobSteps jobId={ID} steps={running()} />);
    expect(rows().map(r => r.getAttribute('data-status'))).toEqual([
      'succeeded',
      'skipped',
      'running',
      'pending',
    ]);
    const done = row('resolve');
    expect(within(done).getByTestId('job-step-icon')).toHaveTextContent(
      'succeeded',
    );
    expect(within(done).getByTestId('job-step-duration')).toHaveTextContent(
      '2s',
    );
    expect(
      within(row('download_10q')).getByTestId('job-step-duration'),
    ).toHaveTextContent('skipped');
    const embed = row('embed');
    expect(within(embed).getByTestId('job-step-counts')).toHaveTextContent(
      '1,240 of 3,400 chunks',
    );
    expect(within(embed).getByTestId('job-step-duration')).toHaveTextContent(
      '1m 05s',
    );
  });

  it('ticks the duration of the running step every second', () => {
    render(<JobSteps jobId={ID} steps={running()} />);
    act(() => {
      vi.advanceTimersByTime(TICK_MS * 3);
    });
    expect(
      within(row('embed')).getByTestId('job-step-duration'),
    ).toHaveTextContent('1m 08s');
  });

  it('opens the running and the failed step by itself', () => {
    const steps = running();
    const {rerender} = render(<JobSteps jobId={ID} steps={steps} />);
    expect(row('embed')).toHaveAttribute('data-open', 'true');
    expect(row('resolve')).toHaveAttribute('data-open', 'false');
    expect(within(row('embed')).getByRole('log')).toHaveTextContent(
      'shard 1/2 ZTS_10K: 20 chunks embedded',
    );
    // The embed step ends: it closes; the next step runs and opens.
    const next = steps.map(s =>
      s.key === 'embed'
        ? {...s, status: 'succeeded' as const, finished_at: T0}
        : s.key === 'reload'
          ? {...s, status: 'failed' as const, log: ['error: reload failed']}
          : s,
    );
    rerender(<JobSteps jobId={ID} steps={next} />);
    expect(row('embed')).toHaveAttribute('data-open', 'false');
    expect(row('reload')).toHaveAttribute('data-open', 'true');
    expect(within(row('reload')).getByRole('log')).toHaveTextContent(
      'error: reload failed',
    );
  });

  it('keeps a step the reader opened or closed as they left it', () => {
    const steps = running();
    const {rerender} = render(<JobSteps jobId={ID} steps={steps} />);
    const toggle = within(row('resolve')).getByTestId('job-step-toggle');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(within(row('resolve')).getByRole('log')).toHaveTextContent(
      'ZTS is CIK 0001555280',
    );
    fireEvent.click(within(row('embed')).getByTestId('job-step-toggle'));
    expect(row('embed')).toHaveAttribute('data-open', 'false');
    rerender(
      <JobSteps
        jobId={ID}
        steps={steps.map(s =>
          s.key === 'embed' ? {...s, log: [...s.log, 'shard 2/2']} : s,
        )}
      />,
    );
    expect(row('embed')).toHaveAttribute('data-open', 'false');
    expect(row('resolve')).toHaveAttribute('data-open', 'true');
  });

  it('says a running step waits for output', () => {
    render(
      <JobSteps
        jobId={ID}
        steps={[jobStep({status: 'running', started_at: T0})]}
      />,
    );
    expect(screen.getByTestId('job-step-log')).toHaveTextContent(
      'Waiting for output.',
    );
  });

  it('follows the newest line until the reader scrolls up', () => {
    const steps = running();
    const {rerender} = render(<JobSteps jobId={ID} steps={steps} />);
    const log = within(row('embed')).getByRole('log');
    let top = 0;
    Object.defineProperty(log, 'scrollHeight', {
      configurable: true,
      get: () => 1000,
    });
    Object.defineProperty(log, 'clientHeight', {
      configurable: true,
      get: () => 200,
    });
    Object.defineProperty(log, 'scrollTop', {
      configurable: true,
      get: () => top,
      set: (value: number) => {
        top = value;
      },
    });
    const grow = (lines: string[]): void =>
      rerender(
        <JobSteps
          jobId={ID}
          steps={steps.map(s => (s.key === 'embed' ? {...s, log: lines} : s))}
        />,
      );
    grow(['a', 'b']);
    expect(top).toBe(1000);
    // The reader scrolls up: new lines no longer move the view.
    top = 300;
    fireEvent.scroll(log);
    grow(['a', 'b', 'c']);
    expect(top).toBe(300);
    // Back at the bottom: it follows again.
    top = 800;
    fireEvent.scroll(log);
    grow(['a', 'b', 'c', 'd']);
    expect(top).toBe(1000);
  });
});

describe('JobCard with steps', () => {
  it('turns the steps to checks in order and stops at the end', async () => {
    const plan = (statuses: JobStep['status'][]): JobStep[] =>
      ['resolve', 'convert', 'embed'].map((key, index) =>
        jobStep({
          key,
          name: key,
          status: statuses[index] ?? 'pending',
          started_at: statuses[index] === 'pending' ? null : T0,
          finished_at:
            statuses[index] === 'succeeded' ? '2026-10-23T10:00:01Z' : null,
        }),
      );
    const states = [
      job({status: 'running', steps: plan(['running', 'pending', 'pending'])}),
      job({
        status: 'running',
        steps: plan(['succeeded', 'running', 'pending']),
      }),
      job({
        status: 'succeeded',
        phase: 'done',
        steps: plan(['succeeded', 'succeeded', 'succeeded']),
        result: {ticker: 'ZTS'},
        log: ['a job log line'],
      }),
    ];
    let served = 0;
    const calls = routeFetch({
      [`GET /api/admin/jobs/${ID}`]: () => ({
        body: states[Math.min(served++, states.length - 1)],
      }),
    });
    render(<JobCard id={ID} />);
    const statuses = (): (string | null)[] =>
      rows().map(r => r.getAttribute('data-status'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(statuses()).toEqual(['running', 'pending', 'pending']);
    expect(screen.getByTestId('job-progress')).toHaveTextContent(
      'step 1 of 3 · 0%',
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });
    expect(statuses()).toEqual(['succeeded', 'running', 'pending']);
    expect(screen.getByTestId('job-phase')).toHaveTextContent('convert');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });
    expect(statuses()).toEqual(['succeeded', 'succeeded', 'succeeded']);
    expect(screen.getByTestId('job-progress')).toHaveTextContent(
      '3 of 3 steps · 100%',
    );
    expect(screen.getByRole('progressbar')).toHaveAttribute(
      'aria-valuenow',
      '100',
    );
    // The steps replace the job log tail.
    expect(screen.queryByTestId('job-log')).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 5);
    });
    expect(calls).toHaveLength(3);
  });

  it('falls back to the log tail for a job without steps', async () => {
    routeFetch({
      [`GET /api/admin/jobs/${ID}`]: {
        body: job({
          status: 'succeeded',
          phase: 'done',
          progress: {done: 2, total: 2},
          log: ['an old line'],
        }),
      },
    });
    render(<JobCard id={ID} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.queryByTestId('job-steps')).toBeNull();
    expect(screen.getByTestId('job-log')).toHaveTextContent('an old line');
    expect(screen.getByTestId('job-progress')).toHaveTextContent('2 of 2');
  });

  it('names the failed step in the progress line', async () => {
    routeFetch({
      [`GET /api/admin/jobs/${ID}`]: {
        body: job({
          status: 'failed',
          phase: 'failed',
          error: 'EdgarFetchError: offline',
          steps: [
            jobStep({key: 'a', status: 'succeeded'}),
            jobStep({key: 'b', status: 'failed', log: ['error: offline']}),
            jobStep({key: 'c', status: 'skipped'}),
          ],
        }),
      },
    });
    render(<JobCard id={ID} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByTestId('job-progress')).toHaveTextContent(
      'failed at step 2 of 3',
    );
    expect(row('b')).toHaveAttribute('data-open', 'true');
  });
});
