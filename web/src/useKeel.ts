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
  PENDING_REQUEST_KEY,
  askStream,
  fetchCoverage,
  fetchIndexStatus,
  fetchReady,
  fetchResult,
  getToken,
  newRequestId,
  readSession,
  setToken,
  writeSession,
} from './api/client';
import type {Action, AppState} from './state';
import {baseState, canAsk, initialState, reducer} from './state';

/** The client route of a stored answer: `/a/{request_id}`. */
const RESULT_ROUTE = /^\/a\/([A-Za-z0-9_-]{1,64})\/?$/;

/** What the page needs from the controller. */
export interface KeelController {
  readonly state: AppState;
  readonly dispatch: Dispatch<Action>;
  readonly hasToken: boolean;
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
    const route = RESULT_ROUTE.exec(window.location.pathname);
    const requestId = route?.[1] ?? readSession(PENDING_REQUEST_KEY);
    if (requestId === null || requestId === undefined || getToken() === null) {
      return;
    }
    let cancelled = false;
    fetchResult(requestId)
      .then(result => {
        if (!cancelled) {
          dispatch({type: 'result_loaded', result});
        }
      })
      .catch(() => undefined)
      .finally(() => writeSession(PENDING_REQUEST_KEY, null));
    return () => {
      cancelled = true;
    };
  }, []);

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
    const run = async (): Promise<void> => {
      try {
        for await (const event of askStream(
          {question},
          requestId,
          controller.signal,
        )) {
          dispatch({type: 'sse', event});
          if (event.event === 'final' || event.event === 'error') {
            writeSession(PENDING_REQUEST_KEY, null);
          }
          if (
            event.event === 'final' ||
            event.event === 'error' ||
            event.event === 'done'
          ) {
            break;
          }
        }
      } catch (error: unknown) {
        writeSession(PENDING_REQUEST_KEY, null);
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

  return {state, dispatch, hasToken, ask, saveToken, reload};
}
