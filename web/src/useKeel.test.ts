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
      if (path.startsWith('/api/results/')) {
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
});
