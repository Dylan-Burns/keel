import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {ESTIMATE, routeFetch, submitted} from '../../testing/admin';
import {MaintenancePanel} from './MaintenancePanel';

afterEach(() => {
  vi.unstubAllGlobals();
});

function posts(calls: ReturnType<typeof routeFetch>): unknown[] {
  return calls.filter(c => c.method === 'POST').map(c => c.body);
}

describe('MaintenancePanel', () => {
  it('rebuilds the index only after typing rebuild', async () => {
    const calls = routeFetch({
      'POST /api/admin/jobs': {status: 202, body: submitted({kind: 'index'})},
    });
    render(<MaintenancePanel onDone={vi.fn()} />);
    fireEvent.click(screen.getByTestId('index-rebuild'));
    expect(screen.getByTestId('index-confirm')).toHaveTextContent('6.6 GB');
    const submit = screen.getByTestId('index-confirm-submit');
    fireEvent.change(screen.getByTestId('index-confirm-input'), {
      target: {value: 'Rebuild'},
    });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByTestId('index-confirm-input'), {
      target: {value: 'rebuild'},
    });
    fireEvent.click(submit);
    await waitFor(() =>
      expect(posts(calls)).toEqual([
        {kind: 'index', params: {incremental: false}, confirm: 'rebuild'},
      ]),
    );
  });

  it('shows the eval cost and sends confirm cost only after the tick', async () => {
    const calls = routeFetch({
      'GET /api/admin/costs/preview': {body: ESTIMATE},
      'POST /api/admin/jobs': {status: 202, body: submitted({kind: 'eval'})},
    });
    render(<MaintenancePanel onDone={vi.fn()} />);
    fireEvent.click(screen.getByTestId('eval-answers'));
    fireEvent.click(screen.getByTestId('eval-run'));
    expect(await screen.findByTestId('eval-confirm-usd')).toHaveTextContent(
      '$4.26',
    );
    expect(calls[0]?.path).toBe(
      '/api/admin/costs/preview?kind=eval&answers=true&judge=true',
    );
    const submit = screen.getByTestId('eval-confirm-submit');
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByTestId('eval-confirm-accept'));
    fireEvent.click(submit);
    await waitFor(() =>
      expect(posts(calls)).toEqual([
        {
          kind: 'eval',
          params: {answers: true, judge: true, subset: null, ablation: true},
          confirm: 'cost',
        },
      ]),
    );
  });

  it('runs an eval without answers at once, with no confirmation', async () => {
    const calls = routeFetch({
      'POST /api/admin/jobs': {status: 202, body: submitted({kind: 'eval'})},
    });
    render(<MaintenancePanel onDone={vi.fn()} />);
    fireEvent.click(screen.getByTestId('eval-run'));
    await waitFor(() =>
      expect(posts(calls)).toEqual([
        {
          kind: 'eval',
          params: {answers: false, judge: true, subset: null, ablation: true},
        },
      ]),
    );
  });

  it('warms the cache behind the cost preview, or facts only without it', async () => {
    const calls = routeFetch({
      'GET /api/admin/costs/preview': {
        body: {...ESTIMATE, kind: 'warm_cache', judge_requests: 0, usd: 2.63},
      },
      'POST /api/admin/jobs': {
        status: 202,
        body: submitted({kind: 'warm_cache'}),
      },
    });
    render(<MaintenancePanel onDone={vi.fn()} />);
    fireEvent.click(screen.getByTestId('warm-cache'));
    expect(await screen.findByTestId('warm-confirm-usd')).toHaveTextContent(
      '$2.63',
    );
    expect(calls[0]?.path).toBe(
      '/api/admin/costs/preview?kind=warm_cache&refresh=false&facts_only=false',
    );
    fireEvent.click(screen.getByTestId('warm-confirm-accept'));
    fireEvent.click(screen.getByTestId('warm-confirm-submit'));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0]).toEqual({
      kind: 'warm_cache',
      params: {refresh: false, facts_only: false},
      confirm: 'cost',
    });
    fireEvent.click(screen.getByLabelText('Facts only (no model request)'));
    fireEvent.click(screen.getByTestId('warm-cache'));
    await waitFor(() => expect(posts(calls)).toHaveLength(2));
    expect(posts(calls)[1]).toEqual({
      kind: 'warm_cache',
      params: {refresh: false, facts_only: true},
    });
  });

  it('runs without the tick when the preview asks for no confirmation', async () => {
    const calls = routeFetch({
      'GET /api/admin/costs/preview': {
        body: {
          ...ESTIMATE,
          model_requests: 0,
          judge_requests: 0,
          confirm: null,
        },
      },
      'POST /api/admin/jobs': {status: 202, body: submitted({kind: 'eval'})},
    });
    render(<MaintenancePanel onDone={vi.fn()} />);
    fireEvent.click(screen.getByTestId('eval-answers'));
    fireEvent.click(screen.getByTestId('eval-run'));
    expect(
      await screen.findByText('This run makes no model request.'),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('eval-confirm-submit'));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0]).not.toHaveProperty('confirm');
  });
});
