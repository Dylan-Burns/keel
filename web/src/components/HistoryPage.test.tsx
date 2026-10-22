import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../api/client';
import type {HistoryResponse} from '../api/types';
import {HISTORY, HISTORY_ADMIN, QUESTION_1} from '../testing/fixtures';
import {HistoryPage} from './HistoryPage';

const assign = vi.fn();

function serve(byScope: Record<string, HistoryResponse>, status = 200): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) => {
      const scope = new URL(path, 'http://x').searchParams.get('scope') ?? '';
      const body = byScope[scope];
      return Promise.resolve(
        body !== undefined && status === 200
          ? new Response(JSON.stringify(body))
          : new Response('{"detail":{"code":"unauthorized","message":"no"}}', {
              status,
            }),
      );
    }),
  );
}

beforeEach(() => {
  assign.mockReset();
  vi.stubGlobal('location', {...window.location, assign});
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

describe('HistoryPage', () => {
  it('lists the questions of the user newest first', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    serve({own: HISTORY});
    render(<HistoryPage />);
    const items = await screen.findAllByTestId('history-item');
    expect(items.map(i => i.getAttribute('data-request-id'))).toEqual([
      'req-2',
      'req-1',
    ]);
    expect(screen.getByTestId('history-user')).toHaveTextContent(
      'Questions of alice',
    );
    const [newest, oldest] = items as [HTMLElement, HTMLElement];
    expect(newest).toHaveTextContent('NVDA');
    expect(newest).toHaveTextContent('$0.0912');
    // An analyst has no switch to every user's questions.
    expect(screen.queryByTestId('history-scope')).toBeNull();
    // A stored answer opens at its link; an expired one cannot.
    fireEvent.click(within(newest).getByTestId('history-open'));
    expect(assign).toHaveBeenCalledWith('/a/req-2');
    expect(within(oldest).getByTestId('history-open')).toBeDisabled();
    expect(within(oldest).getByTestId('history-copy-link')).toBeDisabled();
  });

  it('asks a question again through the re-run link', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    serve({own: HISTORY});
    render(<HistoryPage />);
    const items = await screen.findAllByTestId('history-item');
    fireEvent.click(
      within(items[1] as HTMLElement).getByTestId('history-rerun'),
    );
    expect(assign).toHaveBeenCalledWith(
      `/?rerun=${encodeURIComponent(QUESTION_1)}`,
    );
  });

  it('copies the shareable link of an answer', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal('navigator', {onLine: true, clipboard: {writeText}});
    serve({own: HISTORY});
    render(<HistoryPage />);
    const items = await screen.findAllByTestId('history-item');
    const copy = within(items[0] as HTMLElement).getByTestId(
      'history-copy-link',
    );
    fireEvent.click(copy);
    await waitFor(() => expect(copy).toHaveTextContent('Link copied'));
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/a/req-2`);
  });

  it('lets an admin switch to every user', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    serve({
      own: {...HISTORY_ADMIN, items: []},
      all: {...HISTORY_ADMIN, scope: 'all'},
    });
    render(<HistoryPage />);
    expect(await screen.findByTestId('history-empty')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('history-scope'));
    const items = await screen.findAllByTestId('history-item');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('alice');
    expect(screen.getByTestId('history-user')).toHaveTextContent(
      'Questions of every user',
    );
  });

  it('asks for a token without one, and after a rejected token', async () => {
    render(<HistoryPage />);
    expect(screen.getByTestId('history-page')).toHaveAttribute(
      'data-load',
      'no_token',
    );
    window.sessionStorage.setItem(TOKEN_KEY, 'bad');
    serve({}, 401);
    render(<HistoryPage />);
    await waitFor(() =>
      expect(screen.getAllByTestId('history-page')[1]).toHaveAttribute(
        'data-load',
        'no_token',
      ),
    );
  });

  it('shows an error when the history cannot load', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    serve({}, 500);
    render(<HistoryPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The history could not load.',
    );
  });
});
