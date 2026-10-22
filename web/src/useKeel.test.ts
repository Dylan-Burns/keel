import {act, renderHook, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {
  PENDING_QUESTION_KEY,
  PENDING_REQUEST_KEY,
  TOKEN_KEY,
} from './api/client';
import {
  COVERAGE,
  INDEX_STATUS,
  READY,
  RESPONSE_2,
  eventsFor,
  toSseText,
} from './testing/fixtures';
import {useKeel} from './useKeel';

function respond(askBody: string, results: Response[] = []): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) => {
      if (path === '/api/ready') {
        return Promise.resolve(new Response(JSON.stringify(READY)));
      }
      if (path === '/api/coverage') {
        return Promise.resolve(new Response(JSON.stringify(COVERAGE)));
      }
      if (path === '/api/index/status') {
        return Promise.resolve(new Response(JSON.stringify(INDEX_STATUS)));
      }
      if (path.startsWith('/api/results/') || path.startsWith('/api/shared/')) {
        return Promise.resolve(
          results.shift() ?? new Response('{}', {status: 404}),
        );
      }
      return Promise.resolve(
        new Response(askBody, {headers: {'Content-Type': 'text/event-stream'}}),
      );
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.history.replaceState(null, '', '/');
  window.sessionStorage.clear();
});

describe('useKeel', () => {
  it('streams an answer to complete and clears the pending request', async () => {
    respond(toSseText(eventsFor(RESPONSE_2)));
    const {result} = renderHook(() => useKeel());
    await waitFor(() =>
      expect(result.current.state.service.ready).not.toBeNull(),
    );
    act(() => result.current.ask('How has NVIDIA revenue changed?'));
    await waitFor(() => expect(result.current.state.ui.kind).toBe('complete'));
    expect(window.sessionStorage.getItem(PENDING_REQUEST_KEY)).toBeNull();
  });

  it('asks for a live answer, never the answer cache', async () => {
    respond(toSseText(eventsFor(RESPONSE_2)));
    const {result} = renderHook(() => useKeel());
    await waitFor(() =>
      expect(result.current.state.service.ready).not.toBeNull(),
    );
    act(() => result.current.ask('How has NVIDIA revenue changed?'));
    await waitFor(() => expect(result.current.state.ui.kind).toBe('complete'));
    const calls = vi.mocked(fetch).mock.calls;
    const ask = calls.find(([path]) => path === '/api/ask');
    const body: unknown = JSON.parse(String(ask?.[1]?.body));
    expect(body).toEqual({
      question: 'How has NVIDIA revenue changed?',
      options: {use_cache: false},
    });
  });

  it('ends in provider_down when the body closes without an end event', async () => {
    respond(toSseText(eventsFor(RESPONSE_2).slice(0, 4)));
    const {result} = renderHook(() => useKeel());
    await waitFor(() =>
      expect(result.current.state.service.ready).not.toBeNull(),
    );
    act(() => result.current.ask('How has NVIDIA revenue changed?'));
    await waitFor(() =>
      expect(result.current.state.ui.kind).toBe('provider_down'),
    );
    expect(window.sessionStorage.getItem(PENDING_REQUEST_KEY)).toBeNull();
  });

  it('polls a stored result after a refresh until it exists (E-F-04)', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 't');
    window.sessionStorage.setItem(PENDING_REQUEST_KEY, RESPONSE_2.request_id);
    window.sessionStorage.setItem(PENDING_QUESTION_KEY, 'Q2?');
    respond('', [
      new Response('{}', {status: 404}),
      new Response(JSON.stringify(RESPONSE_2)),
    ]);
    const {result} = renderHook(() => useKeel());
    await waitFor(() => expect(result.current.state.ui.kind).toBe('complete'), {
      timeout: 3000,
    });
    expect(window.sessionStorage.getItem(PENDING_REQUEST_KEY)).toBeNull();
    const ui = result.current.state.ui;
    expect(ui.kind === 'complete' && ui.run.question).toBe('Q2?');
  });

  it('opens a shared answer at /a/{request_id} with its question', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 't');
    window.history.replaceState(null, '', `/a/${RESPONSE_2.request_id}`);
    respond('', [
      new Response(JSON.stringify({...RESPONSE_2, question: 'Stored Q?'})),
    ]);
    const {result} = renderHook(() => useKeel());
    expect(result.current.shared).toBe('loading');
    await waitFor(() => expect(result.current.shared).toBe('loaded'));
    const ui = result.current.state.ui;
    expect(ui.kind === 'complete' && ui.run.question).toBe('Stored Q?');
  });

  it('stops at once on a link that no store holds', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 't');
    window.history.replaceState(null, '', '/a/gone');
    const notFound = new Response(
      JSON.stringify({detail: {code: 'not_found', message: 'no answer'}}),
      {status: 404},
    );
    respond('', [notFound]);
    const {result} = renderHook(() => useKeel());
    await waitFor(() => expect(result.current.shared).toBe('missing'));
    expect(result.current.state.ui.kind).toBe('empty');
  });
});
