import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {setAccessMode} from './api/access';
import {setApiKey} from './api/apiKey';
import type {SseEvent} from './api/types';
import {App} from './App';
import {
  COVERAGE,
  INDEX_STATUS,
  READY,
  RESPONSE_2,
  eventsFor,
  toSseText,
} from './testing/fixtures';

const KEY = 'sk-ant-api03-abcdefghijklmnop_QRST-wxyz';

beforeEach(() => setAccessMode('public'));

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessMode(null);
  window.sessionStorage.clear();
  window.localStorage.clear();
});

/**
 * Stubs fetch for a public service: the JSON endpoints, and `ask` as the
 * given response.
 */
function serve(ask: () => Response): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((path: string) => {
    const bodies: Record<string, unknown> = {
      '/api/ready': {...READY, access: 'public'},
      '/api/coverage': COVERAGE,
      '/api/index/status': INDEX_STATUS,
      '/api/templates': {items: []},
    };
    if (path in bodies) {
      return Promise.resolve(new Response(JSON.stringify(bodies[path])));
    }
    return Promise.resolve(ask());
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function askQuestion(text: string): void {
  fireEvent.change(screen.getByRole('textbox', {name: 'Question'}), {
    target: {value: text},
  });
  fireEvent.click(screen.getByRole('button', {name: 'Ask'}));
}

describe('App on a public service', () => {
  it('shows the API key control and loads coverage without a token', async () => {
    const fetchMock = serve(() => new Response('{}'));
    render(<App />);
    expect(screen.getByTestId('api-key-button')).toBeInTheDocument();
    expect(screen.queryByLabelText('Access token')).toBeNull();
    await waitFor(() =>
      expect(fetchMock.mock.calls.map(([path]) => path)).toContain(
        '/api/coverage',
      ),
    );
    for (const [, init] of fetchMock.mock.calls as [
      string,
      RequestInit | undefined,
    ][]) {
      expect(init?.headers ?? {}).not.toHaveProperty('Authorization');
    }
    // A visitor does not see the links of the pages that need a token.
    expect(screen.queryByTestId('debug-link')).toBeNull();
    expect(screen.queryByTestId('companies-link')).toBeNull();
    expect(screen.getByTestId('history-link')).toBeInTheDocument();
  });

  it('prompts for a key on api_key_required, not for a token', async () => {
    serve(
      () =>
        new Response(
          JSON.stringify({
            detail: {
              code: 'api_key_required',
              message: 'add your Anthropic API key to ask a new question',
            },
          }),
          {status: 401},
        ),
    );
    render(<App />);
    askQuestion('A new question?');
    const prompt = await screen.findByTestId('api-key-prompt');
    expect(prompt).toHaveAttribute('data-code', 'api_key_required');
    expect(screen.queryByTestId('banner-provider-down')).toBeNull();
    expect(screen.queryByText(/Token rejected/)).toBeNull();
    fireEvent.click(screen.getByTestId('api-key-prompt-open'));
    expect(await screen.findByTestId('api-key-settings')).toBeInTheDocument();
    // The question stays in the box for Ask again.
    expect(screen.getByRole('textbox', {name: 'Question'})).toHaveValue(
      'A new question?',
    );
  });

  it('prompts for a new key when Anthropic rejects it', async () => {
    setApiKey(KEY, false);
    const meta = eventsFor(RESPONSE_2)[0];
    const events: SseEvent[] = [
      ...(meta === undefined ? [] : [meta]),
      {
        event: 'error',
        data: {
          code: 'provider_auth_rejected',
          message: 'Anthropic rejected the API key',
        },
      },
    ];
    const fetchMock = serve(
      () =>
        new Response(toSseText(events), {
          headers: {'Content-Type': 'text/event-stream'},
        }),
    );
    render(<App />);
    askQuestion('A new question?');
    const prompt = await screen.findByTestId('api-key-prompt');
    expect(prompt).toHaveAttribute('data-code', 'provider_auth_rejected');
    expect(prompt).toHaveTextContent('Anthropic rejected the API key.');
    const ask = fetchMock.mock.calls.find(([path]) => path === '/api/ask') as
      [string, RequestInit] | undefined;
    expect(ask?.[1].headers).toMatchObject({'X-Anthropic-Api-Key': KEY});
  });
});
