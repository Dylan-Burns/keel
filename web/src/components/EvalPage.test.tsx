import {render, screen, waitFor, within} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../api/client';
import type {EvalResponse} from '../api/types';
import {EVAL_PAGE, EVAL_PAGE_EMPTY} from '../testing/fixtures';
import {EvalPage} from './EvalPage';

function serve(body: EvalResponse | null, status = 200): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) =>
      Promise.resolve(
        path === '/api/eval' && body !== null
          ? new Response(JSON.stringify(body), {status})
          : new Response('{"code":"unauthorized","message":"no"}', {
              status: body === null ? status : 404,
            }),
      ),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('EvalPage', () => {
  it('shows each number before its bar grows and turns a missed gate red at the end', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    serve(EVAL_PAGE);
    render(<EvalPage />);
    const gates = await screen.findAllByTestId('eval-gate');
    expect(gates).toHaveLength(3);
    const [recall, mrr, faithfulness] = gates as [
      HTMLElement,
      HTMLElement,
      HTMLElement,
    ];
    // The value is in the DOM at the first render, before any animation.
    expect(within(recall).getByTestId('eval-gate-value')).toHaveTextContent(
      '0.63 (gate >= 0.85)',
    );
    expect(recall).toHaveAttribute('data-state', 'fail');
    await waitFor(() => expect(recall).toHaveAttribute('data-red', 'true'), {
      timeout: 2000,
    });
    expect(mrr).toHaveAttribute('data-red', 'false');
    expect(faithfulness).toHaveAttribute('data-state', 'pending');
    expect(faithfulness).toHaveTextContent('pending');
  });

  it('renders both documents read-only through the sanitizer', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    serve(EVAL_PAGE);
    render(<EvalPage />);
    const report = await screen.findByTestId('eval-report');
    expect(
      within(report).getByRole('heading', {name: 'Regression gates'}),
    ).toBeInTheDocument();
    expect(report.querySelector('table')).not.toBeNull();
    expect(report.querySelector('script')).toBeNull();
    expect(report).toHaveTextContent(
      '<script>window.keelPwned = true</script>',
    );
    const log = screen.getByTestId('eval-prompt-log');
    expect(log).toHaveTextContent('1.3.0');
    expect(log).toHaveTextContent('docs/PROMPT_LOG.md');
  });

  it('shows a clear empty state when the report is missing', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    serve(EVAL_PAGE_EMPTY);
    render(<EvalPage />);
    const report = await screen.findByTestId('eval-report');
    expect(within(report).getByTestId('eval-empty')).toHaveTextContent(
      'Run keel eval',
    );
    expect(screen.getByTestId('eval-no-gates')).toBeInTheDocument();
    expect(screen.getByTestId('eval-prompt-log')).toHaveTextContent('1.3.0');
  });

  it('asks for the token without one and after a 401', async () => {
    serve(EVAL_PAGE);
    const {unmount} = render(<EvalPage />);
    expect(screen.getByTestId('eval-page')).toHaveAttribute(
      'data-load',
      'no_token',
    );
    unmount();
    window.sessionStorage.setItem(TOKEN_KEY, 'wrong');
    serve(null, 401);
    render(<EvalPage />);
    await waitFor(() =>
      expect(screen.getByTestId('eval-page')).toHaveAttribute(
        'data-load',
        'no_token',
      ),
    );
  });

  it('reports a server error', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    serve(null, 500);
    render(<EvalPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'could not load',
    );
  });
});
