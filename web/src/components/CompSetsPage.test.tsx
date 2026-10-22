import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../api/client';
import type {CompSetItem} from '../api/types';
import {CompSetsPage} from './CompSetsPage';

const SOFTWARE: CompSetItem = {
  name: 'software',
  tickers: ['MSFT', 'ORCL', 'WDAY'],
  owner: 'alice',
  updated_at: '2026-10-21T10:00:00+00:00',
  missing: ['WDAY'],
  editable: true,
};
const BANKS: CompSetItem = {
  name: 'banks',
  tickers: ['JPM', 'BAC'],
  owner: null,
  updated_at: '2026-10-21T10:00:00+00:00',
  missing: [],
  editable: false,
};

interface Call {
  readonly path: string;
  readonly method: string;
  readonly body: unknown;
}

function serve(
  items: CompSetItem[],
  answer: (call: Call) => Response = () =>
    new Response(JSON.stringify(SOFTWARE)),
): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string, init?: RequestInit) => {
      const call = {
        path,
        method: init?.method ?? 'GET',
        body: init?.body === undefined ? null : JSON.parse(String(init.body)),
      };
      calls.push(call);
      if (call.method === 'GET') {
        return Promise.resolve(new Response(JSON.stringify({items})));
      }
      return Promise.resolve(answer(call));
    }),
  );
  return calls;
}

beforeEach(() => {
  vi.stubGlobal('location', {...window.location, assign: vi.fn()});
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

describe('CompSetsPage', () => {
  it('lists the sets with their phrase, tickers, and missing tickers', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    serve([BANKS, SOFTWARE]);
    render(<CompSetsPage />);
    const items = await screen.findAllByTestId('compset-item');
    expect(items).toHaveLength(2);
    const [banks, software] = items as [HTMLElement, HTMLElement];
    expect(software).toHaveTextContent('my software comps');
    expect(software).toHaveTextContent('MSFT ORCL WDAY');
    expect(within(software).getByTestId('compset-missing')).toHaveTextContent(
      'WDAY',
    );
    // A set of another user has no edit or delete button.
    expect(within(banks).queryByTestId('compset-delete')).toBeNull();
    expect(banks).toHaveTextContent('admin');
  });

  it('saves a set and shows the phrase to ask with', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    const calls = serve([]);
    render(<CompSetsPage />);
    await screen.findByTestId('compset-empty');
    fireEvent.change(screen.getByTestId('compset-name'), {
      target: {value: 'software'},
    });
    fireEvent.change(screen.getByTestId('compset-tickers'), {
      target: {value: 'msft, orcl wday'},
    });
    fireEvent.click(screen.getByTestId('compset-save'));
    expect(await screen.findByTestId('compset-notice')).toHaveTextContent(
      'Saved. Ask about "my software comps". Not in the index yet: WDAY',
    );
    const put = calls.find(c => c.method === 'PUT');
    expect(put?.path).toBe('/api/compsets/software');
    expect(put?.body).toEqual({tickers: ['MSFT', 'ORCL', 'WDAY']});
  });

  it('asks for a name and a ticker before a save', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    const calls = serve([]);
    render(<CompSetsPage />);
    await screen.findByTestId('compset-empty');
    fireEvent.click(screen.getByTestId('compset-save'));
    expect(screen.getByTestId('compset-notice')).toHaveTextContent(
      'Give a name and at least 1 ticker.',
    );
    expect(calls.every(c => c.method === 'GET')).toBe(true);
  });

  it('edits and deletes a set, and explains a refusal', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    const calls = serve([SOFTWARE], call =>
      call.method === 'DELETE'
        ? new Response(null, {status: 204})
        : new Response('{"detail":{"code":"forbidden","message":"no"}}', {
            status: 403,
          }),
    );
    render(<CompSetsPage />);
    fireEvent.click(await screen.findByTestId('compset-edit'));
    expect(screen.getByTestId('compset-tickers')).toHaveValue(
      'MSFT, ORCL, WDAY',
    );
    fireEvent.click(screen.getByTestId('compset-save'));
    expect(await screen.findByTestId('compset-notice')).toHaveTextContent(
      'Only the owner of this comp set or an admin can change it.',
    );
    fireEvent.click(screen.getByTestId('compset-delete'));
    await waitFor(() =>
      expect(screen.getByTestId('compset-notice')).toHaveTextContent(
        'Deleted software.',
      ),
    );
    expect(calls.some(c => c.method === 'DELETE')).toBe(true);
  });

  it('asks for a token, then loads', async () => {
    serve([SOFTWARE]);
    render(<CompSetsPage />);
    expect(screen.getByTestId('compsets-page')).toHaveAttribute(
      'data-load',
      'no_token',
    );
  });
});
