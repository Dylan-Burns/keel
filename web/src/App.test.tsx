import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {RERUN_QUESTION_KEY, TOKEN_KEY} from './api/client';
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

const TEMPLATES = {
  items: [
    {
      id: 'risk_benchmark',
      label: 'Risk benchmark',
      text: 'What are the risks of {companies} in {period}?',
      default_period: 'the latest fiscal year',
    },
  ],
};

function serveAll(
  extra: Record<string, unknown> = {},
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((path: string) => {
    const bodies: Record<string, unknown> = {
      '/api/ready': READY,
      '/api/coverage': COVERAGE,
      '/api/index/status': INDEX_STATUS,
      ...extra,
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
    await waitFor(() =>
      expect(screen.getByTestId('index-version')).toHaveTextContent(
        'index 1.0.0',
      ),
    );
  });

  it('never sends a question from the URL', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 't');
    window.history.replaceState(null, '', '/?rerun=Spend%20money%3F&q=x');
    const fetchMock = serveAll();
    render(<App />);
    await waitFor(() =>
      expect(screen.getByTestId('index-version')).toHaveTextContent(
        'index 1.0.0',
      ),
    );
    await new Promise(resolve => setTimeout(resolve, 200));
    const paths = fetchMock.mock.calls.map(([path]) => path);
    expect(paths).not.toContain('/api/ask');
    expect(screen.getByRole('textbox', {name: 'Question'})).toHaveValue('');
  });

  it('prefills the Re-run question without asking, then shares the answer', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 't');
    window.sessionStorage.setItem(RERUN_QUESTION_KEY, 'Q again?');
    const fetchMock = serveAll();
    const writeText = vi.fn(() => Promise.resolve());
    // The spread loses the prototype getter `onLine`, so set it.
    vi.stubGlobal('navigator', {onLine: true, clipboard: {writeText}});
    render(<App />);
    const box = screen.getByRole('textbox', {name: 'Question'});
    expect(box).toHaveValue('Q again?');
    expect(window.sessionStorage.getItem(RERUN_QUESTION_KEY)).toBeNull();
    await waitFor(() =>
      expect(screen.getByTestId('index-version')).toHaveTextContent(
        'index 1.0.0',
      ),
    );
    const isAsk = ([path]: unknown[]): boolean => path === '/api/ask';
    expect(fetchMock.mock.calls.filter(isAsk)).toHaveLength(0);
    // Before an answer the footer and its buttons do not show.
    expect(screen.queryByTestId('share-link')).toBeNull();
    fireEvent.click(screen.getByRole('button', {name: 'Ask'}));
    const share = await screen.findByTestId('share-link');
    await waitFor(() => expect(share).toBeEnabled());
    const asks = fetchMock.mock.calls.filter(isAsk);
    expect(asks).toHaveLength(1);
    expect(JSON.parse(String(asks[0]?.[1]?.body))).toEqual({
      question: 'Q again?',
      options: {use_cache: false},
    });
    fireEvent.click(share);
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        `${window.location.origin}/a/${RESPONSE_2.request_id}`,
      ),
    );
    expect(await screen.findByText('Link copied')).toBeInTheDocument();
  });

  it('fills a template into the box, then takes a vote on the answer', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 't');
    const fetchMock = serveAll({
      '/api/templates': TEMPLATES,
      '/api/feedback': {
        request_id: RESPONSE_2.request_id,
        vote: 'up',
        note: null,
        user: 'alice',
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('template-button'));
    fireEvent.change(screen.getByTestId('template-companies'), {
      target: {value: 'my software comps'},
    });
    fireEvent.click(screen.getByTestId('template-fill'));
    const box = screen.getByRole('textbox', {name: 'Question'});
    expect(box).toHaveValue(
      'What are the risks of my software comps in the latest fiscal year?',
    );
    const isAsk = ([path]: unknown[]): boolean => path === '/api/ask';
    expect(fetchMock.mock.calls.filter(isAsk)).toHaveLength(0);
    expect(screen.queryByTestId('feedback-bar')).toBeNull();
    fireEvent.click(screen.getByRole('button', {name: 'Ask'}));
    fireEvent.click(await screen.findByTestId('feedback-up'));
    expect(await screen.findByText('Thanks: vote saved.')).toBeInTheDocument();
    const vote = fetchMock.mock.calls.find(
      ([path]) => path === '/api/feedback',
    );
    expect(JSON.parse(String(vote?.[1]?.body))).toMatchObject({
      request_id: RESPONSE_2.request_id,
      vote: 'up',
    });
  });
});
