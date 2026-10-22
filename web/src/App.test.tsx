import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from './api/client';
import {App} from './App';
import {
  COVERAGE,
  INDEX_STATUS,
  READY,
  RESPONSE_2,
  eventsFor,
  toSseText,
} from './testing/fixtures';

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
  window.sessionStorage.clear();
});

function serveAll(): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((path: string) => {
    const bodies: Record<string, unknown> = {
      '/api/ready': READY,
      '/api/coverage': COVERAGE,
      '/api/index/status': INDEX_STATUS,
    };
    if (path in bodies) {
      return Promise.resolve(new Response(JSON.stringify(bodies[path])));
    }
    return Promise.resolve(
      new Response(toSseText(eventsFor(RESPONSE_2)), {
        headers: {'Content-Type': 'text/event-stream'},
      }),
    );
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('App', () => {
  it('renders the name Keel as the page heading and the example chips', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(READY))),
    );
    render(<App />);
    expect(
      screen.getByRole('heading', {level: 1, name: 'Keel'}),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId('example-chip')).toHaveLength(3);
    expect(await screen.findByText('index 1.0.0')).toBeInTheDocument();
  });

  it('asks a question from the re-run link once, then copies its share link', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 't');
    window.history.replaceState(null, '', '/?rerun=Q%20again%3F');
    const fetchMock = serveAll();
    const writeText = vi.fn(() => Promise.resolve());
    // The spread loses the prototype getter `onLine`, so set it.
    vi.stubGlobal('navigator', {onLine: true, clipboard: {writeText}});
    render(<App />);
    const share = screen.getByTestId('share-link');
    expect(share).toBeDisabled();
    await waitFor(() => expect(share).toBeEnabled());
    const asks = fetchMock.mock.calls.filter(([path]) => path === '/api/ask');
    expect(asks).toHaveLength(1);
    expect(JSON.parse(String(asks[0]?.[1]?.body))).toEqual({
      question: 'Q again?',
    });
    expect(window.location.search).toBe('');
    fireEvent.click(share);
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        `${window.location.origin}/a/${RESPONSE_2.request_id}`,
      ),
    );
    expect(await screen.findByText('Link copied')).toBeInTheDocument();
  });
});
