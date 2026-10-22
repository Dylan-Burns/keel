/**
 * The 2 modes of the end-to-end specs.
 *
 * Live (KEEL_E2E_BASE_URL set): the specs run against `keel serve` with the
 * mock provider and the mini index. The page gets the token from
 * KEEL_API_TOKEN, and a state is driven by the fault header `X-Keel-Mock`.
 *
 * Mocked (no KEEL_E2E_BASE_URL): the specs run against `vite preview`, and
 * Playwright route mocks answer every `/api/*` request with the recorded
 * responses of src/testing/fixtures.ts, honoring the same fault names.
 */
import type {Locator, Page, Route} from '@playwright/test';

import type {
  AskRequest,
  AskResponse,
  HistoryResponse,
  SseEvent,
} from '../../src/api/types';
import {
  COVERAGE,
  EVAL_PAGE,
  INDEX_STATUS,
  INDEX_STATUS_STALE,
  QUESTION_2,
  READY,
  READY_NO_INDEX,
  RESPONSE_1,
  RESPONSE_2,
  RESPONSE_OUT_OF_SCOPE,
  eventsFor,
  toSseText,
} from '../../src/testing/fixtures';

/** True when the specs run against a real `keel serve`. */
export const isLive = process.env['KEEL_E2E_BASE_URL'] !== undefined;

/** The token the page stores; CI starts `keel serve` with the same value. */
export const TOKEN = process.env['KEEL_API_TOKEN'] ?? 'e2e-token';

/** The fault names of the mock provider header `X-Keel-Mock` (14.9). */
export type Fault =
  | 'partial_coverage'
  | 'out_of_scope'
  | 'rate_limited'
  | 'provider_unavailable'
  | 'index_not_built'
  | 'stale_index'
  | 'script_injection';

/** The script the injection fault puts in the answer and the chunk URL. */
export const INJECTED_SCRIPT = '<script>window.keelPwned = true</script>';

/** The chunk URL outside https://www.sec.gov of the injection fault. */
export const UNTRUSTED_URL = 'https://evil.example/filing.htm';

/** The answer of the injection fault (mocked mode). */
export const RESPONSE_INJECTION: AskResponse = {
  ...RESPONSE_2,
  request_id: 'req-injection',
  retrieval: {
    ...RESPONSE_2.retrieval,
    chunks: RESPONSE_2.retrieval.chunks.map(c => ({
      ...c,
      sec_url: UNTRUSTED_URL,
    })),
  },
  answer: {
    ...RESPONSE_2.answer,
    direct_answer:
      `Revenue grew. ${INJECTED_SCRIPT} <img src=x onerror="window.keelPwned = true"> ` +
      `[a bad link](${UNTRUSTED_URL})`,
  },
};

/** The history of the mocked mode: the answer of example 2, stored. */
export const MOCK_HISTORY: HistoryResponse = {
  user: 'legacy',
  role: 'admin',
  scope: 'own',
  items: [
    {
      request_id: RESPONSE_2.request_id,
      timestamp: '2026-10-21T10:05:00+00:00',
      question: QUESTION_2,
      user: 'legacy',
      tickers: ['NVDA'],
      outcome: 'answered',
      model: 'mock',
      cost_usd: 0,
      from_cache: false,
      degraded: false,
      stored: true,
    },
  ],
};

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

/** A recorded reply of `POST /api/ask`: the status and the SSE blocks. */
interface AskReply {
  readonly status: number;
  readonly headers: Record<string, string>;
  /** The body in pieces: 1 SSE block per event, or 1 JSON body. */
  readonly blocks: string[];
}

function sseReply(events: readonly SseEvent[]): AskReply {
  return {
    status: 200,
    headers: {'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache'},
    blocks: events.map(e => toSseText([e]).replace(/^: ping\n\n/, '')),
  };
}

function answerFor(question: string): AskResponse {
  return /nvidia/i.test(question) ? RESPONSE_2 : RESPONSE_1;
}

/**
 * The recorded reply of the mock provider for a fault and a question.
 *
 * @param fault The fault or null.
 * @param question The question.
 * @return The reply.
 */
function askReply(fault: Fault | null, question: string): AskReply {
  switch (fault) {
    case 'rate_limited':
      return {
        status: 429,
        headers: {'Retry-After': '3', 'Content-Type': 'application/json'},
        blocks: [
          JSON.stringify({
            code: 'rate_limited',
            message: 'Too many questions.',
            retry_after: 3,
          }),
        ],
      };
    case 'provider_unavailable':
      return sseReply([
        ...eventsFor(RESPONSE_1).slice(0, 3),
        {
          event: 'error',
          data: {
            code: 'provider_unavailable',
            message: 'The model provider did not answer.',
          },
        },
        {event: 'done', data: null},
      ]);
    case 'out_of_scope':
      return sseReply(eventsFor(RESPONSE_OUT_OF_SCOPE));
    case 'partial_coverage':
      return sseReply(eventsFor(RESPONSE_1));
    case 'script_injection':
      return sseReply(eventsFor(RESPONSE_INJECTION));
    default:
      return sseReply(eventsFor(answerFor(question)));
  }
}

async function askRoute(route: Route, fault: Fault | null): Promise<void> {
  const body = route.request().postDataJSON() as AskRequest;
  const reply = askReply(fault, body.question);
  return route.fulfill({
    status: reply.status,
    headers: reply.headers,
    body: reply.blocks.join(''),
  });
}

/**
 * Replays the recorded stream with a pause between events, so the page shows
 * the loading and streaming states as it would against `keel serve`. A route
 * mock delivers a body at once, so the paced replay wraps `fetch` for
 * `POST /api/ask` only; every other request goes through the route mocks.
 */
async function paceAsk(
  page: Page,
  fault: Fault | null,
  paceMs: number,
): Promise<void> {
  const replies = {
    nvidia: askReply(fault, 'nvidia'),
    other: askReply(fault, 'other'),
  };
  await page.addInitScript(
    ({replies, paceMs}) => {
      const original = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        if (!url.endsWith('/api/ask') || init?.method !== 'POST') {
          return original(input, init);
        }
        const question = String(JSON.parse(String(init.body)).question);
        const reply = /nvidia/i.test(question) ? replies.nvidia : replies.other;
        const encoder = new TextEncoder();
        const body = new ReadableStream<Uint8Array>({
          async start(controller) {
            for (const block of reply.blocks) {
              await new Promise(resolve => setTimeout(resolve, paceMs));
              controller.enqueue(encoder.encode(block));
            }
            controller.close();
          },
        });
        return new Response(body, {
          status: reply.status,
          headers: reply.headers,
        });
      };
    },
    {replies, paceMs},
  );
}

async function mockApi(page: Page, fault: Fault | null): Promise<void> {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === '/api/health') {
      return json(route, {status: 'ok', version: '0.0.0-e2e'});
    }
    if (path === '/api/ready') {
      return json(route, fault === 'index_not_built' ? READY_NO_INDEX : READY);
    }
    if (path === '/api/index/status') {
      return json(
        route,
        fault === 'stale_index' ? INDEX_STATUS_STALE : INDEX_STATUS,
      );
    }
    if (path === '/api/coverage') {
      return json(route, COVERAGE);
    }
    if (path === '/api/eval') {
      return json(route, EVAL_PAGE);
    }
    if (path === '/api/ask') {
      return askRoute(route, fault);
    }
    if (path === '/api/history') {
      return json(route, MOCK_HISTORY);
    }
    if (path === `/api/shared/${RESPONSE_2.request_id}`) {
      return json(route, {...RESPONSE_2, question: QUESTION_2});
    }
    if (path.startsWith('/api/chunks/')) {
      const chunkId = decodeURIComponent(path.slice('/api/chunks/'.length));
      const all = [
        ...RESPONSE_1.retrieval.chunks,
        ...RESPONSE_2.retrieval.chunks,
      ];
      const chunk = all.find(c => c.chunk_id === chunkId);
      if (chunk === undefined) {
        return json(route, {code: 'not_found', message: 'No such chunk'}, 404);
      }
      return json(route, {
        ...chunk,
        section_title: 'Risk Factors',
        text: `The full text of ${chunkId}.`,
      });
    }
    return json(route, {code: 'not_found', message: 'Not found'}, 404);
  });
}

/** Options of openKeel. */
export interface OpenOptions {
  /** The mock provider fault to drive a state, or none. */
  readonly fault?: Fault;
  /** Store the token before the page loads (the default). */
  readonly withToken?: boolean;
  /**
   * Mocked mode: the pause between replayed events in milliseconds (default
   * 60). 0 serves the whole stream from the route mock at once.
   */
  readonly paceMs?: number;
  /** The page path to open (default `/`). */
  readonly path?: string;
}

/**
 * Opens the page in the mode of the run, with the token and the fault.
 *
 * @param page The Playwright page.
 * @param options The fault and the token choice.
 */
export async function openKeel(
  page: Page,
  options: OpenOptions = {},
): Promise<void> {
  const fault = options.fault ?? null;
  if (options.withToken !== false) {
    await page.addInitScript(token => {
      window.sessionStorage.setItem('keel.token', token);
    }, TOKEN);
  }
  if (isLive) {
    if (fault !== null) {
      await page.setExtraHTTPHeaders({'X-Keel-Mock': fault});
    }
  } else {
    await mockApi(page, fault);
    const paceMs = options.paceMs ?? 60;
    if (paceMs > 0) {
      await paceAsk(page, fault, paceMs);
    }
  }
  await recordStates(page);
  await page.goto(options.path ?? '/');
}

/**
 * Records every value of the page `data-state` attribute in arrival order
 * into `window.keelStates`, so a spec can check the states it passed.
 *
 * @param page The page.
 */
async function recordStates(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as {keelStates: string[]}).keelStates = seen;
    const note = (value: string | null): void => {
      if (value !== null && seen[seen.length - 1] !== value) {
        seen.push(value);
      }
    };
    new MutationObserver(() => {
      note(
        document.querySelector('[data-state]')?.getAttribute('data-state') ??
          null,
      );
    }).observe(document, {
      attributes: true,
      attributeFilter: ['data-state'],
      childList: true,
      subtree: true,
    });
  });
}

/**
 * The `data-state` values the page passed, in order.
 *
 * @param page The page.
 * @return The states.
 */
export function statesSeen(page: Page): Promise<string[]> {
  return page.evaluate(
    () => (window as unknown as {keelStates: string[]}).keelStates,
  );
}

/**
 * The current UI state of the page.
 *
 * @param page The page.
 * @return The locator of the element that carries `data-state`.
 */
export function stateRoot(page: Page): Locator {
  return page.locator('[data-state]').first();
}
