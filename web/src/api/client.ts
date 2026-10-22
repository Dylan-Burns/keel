/**
 * The Keel API client: `fetch` for the JSON endpoints and a `ReadableStream`
 * parser for the server-sent events of `POST /api/ask`. `EventSource` cannot
 * send the bearer token header, so the stream is read by hand (chapter 14.9).
 */
import type {
  AskRequest,
  AskResponse,
  ChunkResponse,
  CoverageResponse,
  ErrorEvent,
  HealthResponse,
  IndexStatusResponse,
  ReadyResponse,
  SseEvent,
  SseEventName,
} from './types';

/** The session storage key of the bearer token (the only stored secret). */
export const TOKEN_KEY = 'keel.token';

/** The session storage key of the request ID of an answer in flight. */
export const PENDING_REQUEST_KEY = 'keel.pending_request_id';

/** The session storage key of the question of the answer in flight. */
export const PENDING_QUESTION_KEY = 'keel.pending_question';

const EVENT_NAMES: ReadonlySet<string> = new Set<SseEventName>([
  'meta',
  'analysis',
  'retrieval',
  'answer_delta',
  'findings',
  'final',
  'error',
  'done',
]);

/** An HTTP error from the API, with the parsed error body when present. */
export class ApiError extends Error {
  /**
   * @param status The HTTP status code.
   * @param code The error code of the body, or `http_<status>`.
   * @param message The message of the body, or the status text.
   * @param retryAfter Seconds from `Retry-After` or the body, or null.
   */
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryAfter: number | null,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** A raw server-sent event: the event name and the joined data lines. */
export interface RawSseEvent {
  readonly event: string;
  readonly data: string;
}

/**
 * Parses one SSE block (the lines between 2 blank lines).
 *
 * @param block The block text without the trailing blank line.
 * @return The event, or null for a comment-only block (`: ping`).
 */
function parseBlock(block: string): RawSseEvent | null {
  let event = 'message';
  const data: string[] = [];
  let sawField = false;
  for (const line of block.split('\n')) {
    if (line === '' || line.startsWith(':')) {
      continue;
    }
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) {
      value = value.slice(1);
    }
    if (field === 'event') {
      event = value;
      sawField = true;
    } else if (field === 'data') {
      data.push(value);
      sawField = true;
    }
  }
  return sawField ? {event, data: data.join('\n')} : null;
}

/**
 * An incremental SSE parser. Feed it text chunks in arrival order; it
 * returns every event that a blank line closed. A chunk boundary may fall
 * anywhere, inside a line or inside a CRLF pair.
 */
export class SseParser {
  private buffer = '';

  /**
   * Adds a text chunk and returns the events it completed.
   *
   * @param chunk The next decoded text of the stream.
   * @return The completed events, in order.
   */
  push(chunk: string): RawSseEvent[] {
    this.buffer += chunk;
    // Normalize line ends, but keep a trailing CR: its LF may come next.
    const keepCr = this.buffer.endsWith('\r');
    const body = keepCr ? this.buffer.slice(0, -1) : this.buffer;
    const normalized = body.replace(/\r\n?/g, '\n');
    const events: RawSseEvent[] = [];
    let rest = normalized;
    let end = rest.indexOf('\n\n');
    while (end !== -1) {
      const parsed = parseBlock(rest.slice(0, end));
      if (parsed !== null) {
        events.push(parsed);
      }
      rest = rest.slice(end + 2);
      end = rest.indexOf('\n\n');
    }
    this.buffer = keepCr ? `${rest}\r` : rest;
    return events;
  }

  /**
   * Ends the stream and returns a last event that had no closing blank line.
   *
   * @return The last event, or an empty list.
   */
  flush(): RawSseEvent[] {
    const parsed = parseBlock(this.buffer.replace(/\r\n?/g, '\n'));
    this.buffer = '';
    return parsed === null ? [] : [parsed];
  }
}

/**
 * Turns a raw event into a typed event of chapter 14.3.
 *
 * @param raw The raw event.
 * @return The typed event, or null for an unknown event name.
 * @throws SyntaxError When the data of a known event is not JSON.
 */
export function toSseEvent(raw: RawSseEvent): SseEvent | null {
  if (!EVENT_NAMES.has(raw.event)) {
    return null;
  }
  const data: unknown = raw.data.trim() === '' ? null : JSON.parse(raw.data);
  // The server is the schema owner; the cast follows the event name.
  return {event: raw.event, data} as SseEvent;
}

/**
 * Reads a byte stream of server-sent events into typed events.
 *
 * @param body The response body.
 * @yields The typed events in arrival order.
 */
export async function* readSse(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const {done, value} = await reader.read();
      const text = done
        ? decoder.decode()
        : decoder.decode(value, {stream: true});
      const raws = done
        ? [...parser.push(text), ...parser.flush()]
        : parser.push(text);
      for (const raw of raws) {
        const event = toSseEvent(raw);
        if (event !== null) {
          yield event;
        }
      }
      if (done) {
        return;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Reads the token from session storage.
 *
 * @return The token, or null when none is stored or storage is blocked.
 */
export function getToken(): string | null {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/**
 * Stores the token in session storage, or removes it for an empty value.
 *
 * @param token The token.
 */
export function setToken(token: string): void {
  try {
    if (token === '') {
      window.sessionStorage.removeItem(TOKEN_KEY);
    } else {
      window.sessionStorage.setItem(TOKEN_KEY, token);
    }
  } catch {
    // Storage blocked: the token lives for this page only.
  }
}

/**
 * Reads a session storage value without throwing.
 *
 * @param key The key.
 * @return The value or null.
 */
export function readSession(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

/**
 * Writes or removes a session storage value without throwing.
 *
 * @param key The key.
 * @param value The value, or null to remove it.
 */
export function writeSession(key: string, value: string | null): void {
  try {
    if (value === null) {
      window.sessionStorage.removeItem(key);
    } else {
      window.sessionStorage.setItem(key, value);
    }
  } catch {
    // Storage blocked: nothing to keep.
  }
}

/**
 * Makes a new idempotency key (a UUID).
 *
 * @return The key.
 */
export function newRequestId(): string {
  return crypto.randomUUID();
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token === null ? {} : {Authorization: `Bearer ${token}`};
}

function parseRetryAfter(value: string | null): number | null {
  if (value === null) {
    return null;
  }
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

function isErrorBody(value: unknown): value is ErrorEvent {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as {code?: unknown}).code === 'string'
  );
}

/**
 * Builds the ApiError of a failed response.
 *
 * @param response The response with a status outside 200 to 299.
 * @return The error.
 */
export async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  // FastAPI wraps an HTTPException body in `detail`.
  if (
    typeof body === 'object' &&
    body !== null &&
    'detail' in body &&
    isErrorBody((body as {detail: unknown}).detail)
  ) {
    body = (body as {detail: unknown}).detail;
  }
  const header = parseRetryAfter(response.headers.get('Retry-After'));
  if (isErrorBody(body)) {
    return new ApiError(
      response.status,
      body.code,
      body.message,
      header ?? body.retry_after ?? null,
    );
  }
  return new ApiError(
    response.status,
    `http_${response.status}`,
    response.statusText || `HTTP ${response.status}`,
    header,
  );
}

/**
 * GETs a JSON endpoint with the bearer token.
 *
 * @param path The path under the same origin, such as `/api/ready`.
 * @param signal An optional abort signal.
 * @return The parsed JSON.
 * @throws ApiError On an HTTP error or a body that is not JSON.
 */
export async function getJson<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    headers: {Accept: 'application/json', ...authHeaders()},
    ...(signal === undefined ? {} : {signal}),
  });
  if (!response.ok) {
    throw await toApiError(response);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(
      response.status,
      'bad_json',
      'The response is not JSON',
      null,
    );
  }
}

/** `GET /api/health`. @return The health body. */
export const fetchHealth = (): Promise<HealthResponse> =>
  getJson('/api/health');

/** `GET /api/ready`. @return The readiness body. */
export const fetchReady = (): Promise<ReadyResponse> => getJson('/api/ready');

/** `GET /api/index/status`. @return The index status. */
export const fetchIndexStatus = (): Promise<IndexStatusResponse> =>
  getJson('/api/index/status');

/** `GET /api/coverage`. @return The coverage. */
export const fetchCoverage = (): Promise<CoverageResponse> =>
  getJson('/api/coverage');

/**
 * `GET /api/chunks/{chunk_id}`.
 *
 * @param chunkId The chunk ID.
 * @return The chunk.
 */
export const fetchChunk = (chunkId: string): Promise<ChunkResponse> =>
  getJson(`/api/chunks/${encodeURIComponent(chunkId)}`);

/**
 * `GET /api/results/{request_id}`: the stored answer of a request (E-F-04).
 *
 * @param requestId The request ID.
 * @return The answer response.
 */
export const fetchResult = (requestId: string): Promise<AskResponse> =>
  getJson(`/api/results/${encodeURIComponent(requestId)}`);

/**
 * `POST /api/ask` with streaming: yields the server-sent events.
 *
 * @param request The question and the options.
 * @param requestId The idempotency key; the `meta` event echoes it.
 * @param signal An optional abort signal.
 * @yields The typed events.
 * @throws ApiError On an HTTP error before the stream starts.
 */
export async function* askStream(
  request: AskRequest,
  requestId: string,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  const response = await fetch('/api/ask', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'Idempotency-Key': requestId,
      ...authHeaders(),
    },
    body: JSON.stringify(request),
    ...(signal === undefined ? {} : {signal}),
  });
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.body === null) {
    throw new ApiError(
      response.status,
      'empty_body',
      'The stream is empty',
      null,
    );
  }
  yield* readSse(response.body);
}
