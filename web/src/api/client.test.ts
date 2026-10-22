import {afterEach, describe, expect, it, vi} from 'vitest';

import {
  ApiError,
  SseParser,
  TOKEN_KEY,
  askStream,
  fetchReady,
  getToken,
  readSse,
  setToken,
  toSseEvent,
} from './client';
import type {SseEvent} from './types';
import {RESPONSE_1, eventsFor, toSseText} from '../testing/fixtures';

const RECORDED = toSseText(eventsFor(RESPONSE_1));

function streamOf(chunks: readonly string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

async function collect(
  stream: ReadableStream<Uint8Array>,
): Promise<SseEvent[]> {
  const events: SseEvent[] = [];
  for await (const event of readSse(stream)) {
    events.push(event);
  }
  return events;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

describe('SseParser', () => {
  it('parses the recorded stream in order and skips the ping comment', async () => {
    const events = await collect(streamOf([RECORDED]));
    expect(events.map(e => e.event)).toEqual([
      'meta',
      'analysis',
      'retrieval',
      'answer_delta',
      'answer_delta',
      'answer_delta',
      'answer_delta',
      'findings',
      'findings',
      'final',
      'done',
    ]);
    const final = events.find(e => e.event === 'final');
    expect(final?.data).toEqual(RESPONSE_1);
  });

  it('handles a chunk boundary at every position of the stream', async () => {
    const whole = await collect(streamOf([RECORDED]));
    for (let cut = 1; cut < RECORDED.length; cut += 7) {
      const split = await collect(
        streamOf([RECORDED.slice(0, cut), RECORDED.slice(cut)]),
      );
      expect(split).toEqual(whole);
    }
  });

  it('handles 1-byte chunks, including multi-byte UTF-8 characters', async () => {
    const text = 'event: answer_delta\ndata: {"text":"café €"}\n\n';
    const bytes = new TextEncoder().encode(text);
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of bytes) {
          controller.enqueue(new Uint8Array([byte]));
        }
        controller.close();
      },
    });
    const events = await collect(stream);
    expect(events).toEqual([{event: 'answer_delta', data: {text: 'café €'}}]);
  });

  it('accepts CRLF line ends split between chunks', () => {
    const parser = new SseParser();
    expect(parser.push('event: done\r')).toEqual([]);
    expect(parser.push('\ndata: \r\n\r')).toEqual([]);
    expect(parser.push('\n')).toEqual([{event: 'done', data: ''}]);
  });

  it('joins multi-line data and flushes a last event without a blank line', () => {
    const parser = new SseParser();
    expect(
      parser.push('event: answer_delta\ndata: {"text":\ndata: "a"}'),
    ).toEqual([]);
    expect(parser.flush()).toEqual([
      {event: 'answer_delta', data: '{"text":\n"a"}'},
    ]);
  });

  it('drops unknown event names', () => {
    expect(toSseEvent({event: 'surprise', data: '{}'})).toBeNull();
    expect(toSseEvent({event: 'done', data: ''})).toEqual({
      event: 'done',
      data: null,
    });
  });
});

describe('askStream', () => {
  it('sends the bearer token, the Idempotency-Key, and the SSE Accept header', async () => {
    setToken('secret-token');
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(streamOf([RECORDED]), {
        status: 200,
        headers: {'Content-Type': 'text/event-stream'},
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const events: SseEvent[] = [];
    for await (const event of askStream({question: 'q?'}, 'key-1')) {
      events.push(event);
    }
    expect(events).toHaveLength(11);
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe('/api/ask');
    expect(init.method).toBe('POST');
    expect(init.headers).toMatchObject({
      Authorization: 'Bearer secret-token',
      'Idempotency-Key': 'key-1',
      Accept: 'text/event-stream',
    });
    expect(JSON.parse(String(init.body))).toEqual({question: 'q?'});
  });

  it('throws an ApiError with Retry-After on HTTP 429', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({code: 'rate_limited', message: 'Too many'}),
          {
            status: 429,
            headers: {'Retry-After': '30', 'Content-Type': 'application/json'},
          },
        ),
      ),
    );
    const iterator = askStream({question: 'q?'}, 'key-2');
    await expect(iterator.next()).rejects.toMatchObject({
      status: 429,
      code: 'rate_limited',
      retryAfter: 30,
    });
  });

  it('reads a FastAPI detail body and falls back to the status', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({detail: {code: 'unauthorized', message: 'Token'}}),
            {
              status: 401,
            },
          ),
        )
        .mockResolvedValueOnce(new Response('not json', {status: 500})),
    );
    await expect(fetchReady()).rejects.toMatchObject({
      status: 401,
      code: 'unauthorized',
    });
    const error: unknown = await fetchReady().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({status: 500, code: 'http_500'});
  });
});

describe('token storage', () => {
  it('keeps the token in session storage only', () => {
    setToken('abc');
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBe('abc');
    expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(getToken()).toBe('abc');
    setToken('');
    expect(getToken()).toBeNull();
  });
});
