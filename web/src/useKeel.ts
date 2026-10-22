/**
 * The page controller: 1 reducer (state.ts) and the effects around it. It
 * loads the service facts, sends questions, reads the stream, follows the
 * browser online and offline events, runs the rate-limit countdown, and
 * recovers an answer after a refresh mid-stream (E-F-04).
 */
import type {Dispatch} from 'react';
import {useCallback, useEffect, useReducer, useRef, useState} from 'react';

import {
  ApiError,
  PENDING_QUESTION_KEY,
  PENDING_REQUEST_KEY,
  askStream,
  fetchCoverage,
  fetchIndexStatus,
  fetchReady,
  fetchResult,
  fetchShared,
  getToken,
  newRequestId,
  readSession,
  setToken,
  writeSession,
} from './api/client';
import {sharedRequestId} from './lib/links';
import type {Action, AppState} from './state';
import {baseState, canAsk, initialState, reducer} from './state';

/** The pauses between the polls of a stored result after a refresh. */
const RESULT_POLL_MS: readonly number[] = [1000, 2000, 3000, 5000, 8000, 13000];

/**
 * The load state of a shareable link `/a/{request_id}` (chapter 27.2):
 * `none` on any other path, `missing` when no store holds the answer.
 */
export type SharedLoad = 'none' | 'loading' | 'loaded' | 'missing';

/** What the page needs from the controller. */
export interface KeelController {
  readonly state: AppState;
  readonly dispatch: Dispatch<Action>;
  readonly hasToken: boolean;
  /** The load state of the shared answer of the `/a/{request_id}` route. */
  readonly shared: SharedLoad;
  readonly ask: (question: string) => void;
  readonly saveToken: (token: string) => void;
  readonly reload: () => void;
}

function toHttpError(error: ApiError): Action {
  return {
    type: 'http_error',
    status: error.status,
    error: {
      code: error.code,
      message: error.message,
      retry_after: error.retryAfter,
    },
  };
}

/**
 * The page controller hook.
 *
 * @return The state, the dispatch, and the commands.
 */
export function useKeel(): KeelController {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [hasToken, setHasToken] = useState(() => getToken() !== null);
  const [loadCount, setLoadCount] = useState(0);
  const [shared, setShared] = useState<SharedLoad>(() =>
    sharedRequestId(window.location.pathname) === null ? 'none' : 'loading',
  );
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  const abortRef = useRef<AbortController | null>(null);

  // The service facts: ready first (no token), then the token endpoints.
  useEffect(() => {
    let cancelled = false;
    const load = async (): Promise<void> => {
      try {
        const ready = await fetchReady();
        if (cancelled) {
          return;
        }
        dispatch({type: 'ready_loaded', ready});
      } catch {
        if (!cancelled) {
          dispatch({type: 'service_unreachable'});
        }
        return;
      }
      if (getToken() === null) {
        return;
      }
      const results = await Promise.allSettled([
        fetchCoverage(),
        fetchIndexStatus(),
      ]);
      if (cancelled) {
        return;
      }
      const [coverage, status] = results;
      if (coverage.status === 'fulfilled') {
        dispatch({type: 'coverage_loaded', coverage: coverage.value});
      } else if (
        coverage.reason instanceof ApiError &&
        coverage.reason.status === 401
      ) {
        dispatch({type: 'token_rejected'});
      }
      if (status.status === 'fulfilled') {
        dispatch({type: 'index_status_loaded', status: status.value});
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [loadCount]);

  // A stored answer: a refresh mid-stream, or the route /a/{request_id}.
  useEffect(() => {
    const sharedId = sharedRequestId(window.location.pathname);
    const requestId = sharedId ?? readSession(PENDING_REQUEST_KEY);
    if (requestId === null || !hasToken) {
      return;
    }
    const question = readSession(PENDING_QUESTION_KEY);
    let cancelled = false;
    let timer: number | undefined;
    const clear = (): void => {
      writeSession(PENDING_REQUEST_KEY, null);
      writeSession(PENDING_QUESTION_KEY, null);
    };
    // The server stores the answer when it completes, so a refresh mid-stream
    // polls with a growing pause until the result exists (E-F-04).
    const attempt = (n: number): void => {
      // A link reads the shared route, open to any token holder; a refresh
      // reads the caller's own result.
      (sharedId === null ? fetchResult(requestId) : fetchShared(requestId))
        .then(result => {
          if (!cancelled) {
            dispatch({type: 'result_loaded', result, question});
            clear();
            if (sharedId !== null) {
              setShared('loaded');
            }
          }
        })
        .catch((error: unknown) => {
          // A link to an answer that no store holds stops at once; the
          // shared route never reports a running answer.
          const pending =
            error instanceof ApiError &&
            error.status === 404 &&
            sharedId === null;
          if (cancelled) {
            return;
          }
          if (pending && n < RESULT_POLL_MS.length) {
            timer = window.setTimeout(() => attempt(n + 1), RESULT_POLL_MS[n]);
          } else {
            clear();
            if (sharedId !== null) {
              setShared('missing');
            }
          }
        });
    };
    attempt(0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [hasToken]);

  // The browser offline and online events.
  useEffect(() => {
    const offline = (): void => dispatch({type: 'offline'});
    const online = (): void => dispatch({type: 'online'});
    window.addEventListener('offline', offline);
    window.addEventListener('online', online);
    if (!navigator.onLine) {
      offline();
    }
    return () => {
      window.removeEventListener('offline', offline);
      window.removeEventListener('online', online);
    };
  }, []);

  // The rate-limit countdown: 1 tick per second while the state lasts.
  const rateLimited = baseState(state.ui).kind === 'rate_limited';
  useEffect(() => {
    if (!rateLimited) {
      return;
    }
    const timer = window.setInterval(
      () => dispatch({type: 'rate_limit_tick'}),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [rateLimited]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const ask = useCallback((question: string): void => {
    if (!canAsk(stateRef.current.ui)) {
      return;
    }
    const requestId = newRequestId();
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    dispatch({type: 'ask', question, requestId});
    writeSession(PENDING_REQUEST_KEY, requestId);
    writeSession(PENDING_QUESTION_KEY, question);
    const finish = (): void => {
      writeSession(PENDING_REQUEST_KEY, null);
      writeSession(PENDING_QUESTION_KEY, null);
    };
    const run = async (): Promise<void> => {
      let ended = false;
      try {
        for await (const event of askStream(
          {question},
          requestId,
          controller.signal,
        )) {
          dispatch({type: 'sse', event});
          if (
            event.event === 'final' ||
            event.event === 'error' ||
            event.event === 'done'
          ) {
            ended = true;
            break;
          }
        }
        finish();
        if (!ended && !controller.signal.aborted) {
          // The body closed without final, error, or done.
          dispatch({
            type: 'stream_failed',
            message: 'The stream ended before the answer was complete.',
          });
        }
      } catch (error: unknown) {
        finish();
        if (controller.signal.aborted) {
          return;
        }
        if (error instanceof ApiError) {
          dispatch(toHttpError(error));
        } else if (!navigator.onLine) {
          dispatch({type: 'offline'});
        } else {
          dispatch({
            type: 'stream_failed',
            message: 'The connection to the service broke during the answer.',
          });
        }
      }
    };
    void run();
  }, []);

  const saveToken = useCallback((token: string): void => {
    setToken(token);
    setHasToken(getToken() !== null);
    dispatch({type: 'token_set'});
    setLoadCount(count => count + 1);
  }, []);

  const reload = useCallback((): void => setLoadCount(count => count + 1), []);

  return {state, dispatch, hasToken, shared, ask, saveToken, reload};
}
