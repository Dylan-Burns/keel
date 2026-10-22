import {render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../../api/client';
import {job, routeFetch} from '../../testing/admin';
import {JobsPage} from './JobsPage';

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

describe('JobsPage', () => {
  it('lists the jobs and opens the job of the path', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    window.history.replaceState(null, '', '/jobs/3f2a9c0d1e4b5a67');
    const done = job({status: 'succeeded', phase: 'done'});
    routeFetch({
      'GET /api/admin/jobs': {body: {items: [done], active: null}},
      'GET /api/admin/jobs/3f2a9c0d1e4b5a67': {body: done},
    });
    render(<JobsPage />);
    expect(await screen.findByTestId('jobs-row')).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(await screen.findByTestId('job-card')).toHaveAttribute(
      'data-status',
      'succeeded',
    );
  });

  it('names the job that holds the slot', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    window.history.replaceState(null, '', '/jobs');
    const running = job({status: 'running', kind: 'index'});
    routeFetch({
      'GET /api/admin/jobs': {body: {items: [running], active: running}},
    });
    render(<JobsPage />);
    expect(await screen.findByTestId('jobs-active')).toHaveTextContent(
      'The index job',
    );
    expect(screen.queryByTestId('job-card')).toBeNull();
  });

  it('says so when no job ran yet', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    window.history.replaceState(null, '', '/jobs');
    routeFetch({'GET /api/admin/jobs': {body: {items: [], active: null}}});
    render(<JobsPage />);
    expect(await screen.findByTestId('jobs-empty')).toBeInTheDocument();
  });
});
