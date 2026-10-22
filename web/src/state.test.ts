import {describe, expect, it} from 'vitest';

import type {SseEvent} from './api/types';
import type {Action, AppState, UiState, UiStateKind} from './state';
import {
  answerText,
  baseState,
  canAsk,
  currentRun,
  health,
  initialState,
  reducer,
} from './state';
import {
  INDEX_STATUS,
  INDEX_STATUS_STALE,
  QUESTION_1,
  READY,
  READY_NO_INDEX,
  RESPONSE_1,
  RESPONSE_2,
  RESPONSE_OUT_OF_SCOPE,
  eventsFor,
} from './testing/fixtures';

function run(
  actions: readonly Action[],
  from: AppState = initialState,
): AppState {
  return actions.reduce(reducer, from);
}

function ask(question = QUESTION_1, requestId = 'req-1'): Action {
  return {type: 'ask', question, requestId};
}

function sse(events: readonly SseEvent[]): Action[] {
  return events.map(event => ({type: 'sse', event}));
}

const seen = new Set<UiStateKind>();
function kindOf(state: AppState): UiStateKind {
  let ui: UiState = state.ui;
  seen.add(ui.kind);
  while (ui.kind === 'stale_index' || ui.kind === 'network_offline') {
    ui = ui.under;
    seen.add(ui.kind);
  }
  return state.ui.kind;
}

describe('reducer', () => {
  it('starts empty', () => {
    expect(kindOf(initialState)).toBe('empty');
    expect(health(initialState)).toBe('unknown');
  });

  it('goes to loading on ask and lights the steps in event order', () => {
    const events = eventsFor(RESPONSE_2);
    let state = run([{type: 'ready_loaded', ready: READY}, ask()]);
    expect(kindOf(state)).toBe('loading');
    expect(canAsk(state.ui)).toBe(false);
    state = run(sse(events.slice(0, 3)), state);
    expect(kindOf(state)).toBe('loading');
    expect(currentRun(state.ui)?.stepsLit).toEqual([
      'understanding',
      'retrieval',
      'model',
    ]);
    expect(currentRun(state.ui)?.retrieval?.chunks).toHaveLength(1);
  });

  it('goes to streaming on the first answer_delta and joins the deltas', () => {
    const events = eventsFor(RESPONSE_2, 3);
    const deltas = events.filter(e => e.event === 'answer_delta');
    const state = run([ask(), ...sse(events.slice(0, 3 + deltas.length))]);
    expect(kindOf(state)).toBe('streaming');
    const current = currentRun(state.ui);
    expect(current).not.toBeNull();
    if (current !== null) {
      expect(answerText(current)).toBe(RESPONSE_2.answer.direct_answer);
    }
  });

  it('goes to complete on final with full coverage', () => {
    const state = run([
      {type: 'ready_loaded', ready: READY},
      ask(),
      ...sse(eventsFor(RESPONSE_2)),
    ]);
    expect(kindOf(state)).toBe('complete');
    expect(canAsk(state.ui)).toBe(true);
    expect(health(state)).toBe('green');
  });

  it('goes to partial_coverage with a missing company or an unverified finding', () => {
    const state = run([ask(), ...sse(eventsFor(RESPONSE_1))]);
    const ui = state.ui;
    expect(kindOf(state)).toBe('partial_coverage');
    if (ui.kind === 'partial_coverage') {
      expect(ui.companiesMissing).toEqual(['TSLA']);
      expect(ui.unverifiedFindings).toBe(1);
    }
  });

  it('goes to out_of_scope on a refusal', () => {
    const state = run([ask(), ...sse(eventsFor(RESPONSE_OUT_OF_SCOPE))]);
    expect(kindOf(state)).toBe('out_of_scope');
    expect(state.ui.kind === 'out_of_scope' && state.ui.reason).toMatch(
      /does not predict/,
    );
  });

  it('goes to rate_limited on HTTP 429, counts down, and returns', () => {
    let state = run([
      ask(),
      {
        type: 'http_error',
        status: 429,
        error: {code: 'rate_limited', message: 'slow down', retry_after: 2},
      },
    ]);
    expect(kindOf(state)).toBe('rate_limited');
    expect(canAsk(state.ui)).toBe(false);
    state = reducer(state, {type: 'rate_limit_tick'});
    expect(state.ui.kind === 'rate_limited' && state.ui.secondsLeft).toBe(1);
    state = reducer(state, {type: 'rate_limit_tick'});
    expect(kindOf(state)).toBe('empty');
    expect(canAsk(state.ui)).toBe(true);
  });

  it('goes to provider_down on the error event and keeps the chunks', () => {
    const events = eventsFor(RESPONSE_1).slice(0, 3);
    const state = run([
      ask(),
      ...sse(events),
      {
        type: 'sse',
        event: {
          event: 'error',
          data: {
            code: 'provider_unavailable',
            message: 'The model is unavailable.',
          },
        },
      },
    ]);
    expect(kindOf(state)).toBe('provider_down');
    expect(currentRun(state.ui)?.retrieval?.chunks).toHaveLength(2);
    expect(health({...state, service: {...state.service, ready: READY}})).toBe(
      'amber',
    );
  });

  it('goes to provider_down on a degraded final', () => {
    const degraded = {
      ...RESPONSE_2,
      meta: {...RESPONSE_2.meta, degraded: true},
    };
    const state = run([ask(), ...sse(eventsFor(degraded))]);
    expect(kindOf(state)).toBe('provider_down');
  });

  it('shows provider_down before any question without a provider key', () => {
    const state = reducer(initialState, {
      type: 'ready_loaded',
      ready: {...READY, checks: {...READY.checks, provider_key: false}},
    });
    expect(kindOf(state)).toBe('provider_down');
    expect(canAsk(state.ui)).toBe(true);
  });

  it('goes to index_not_built when ready reports no index', () => {
    let state = reducer(initialState, {
      type: 'ready_loaded',
      ready: READY_NO_INDEX,
    });
    expect(kindOf(state)).toBe('index_not_built');
    expect(canAsk(state.ui)).toBe(false);
    expect(health(state)).toBe('red');
    state = reducer(state, {type: 'ready_loaded', ready: READY});
    expect(kindOf(state)).toBe('empty');
  });

  it('wraps stale_index over the answer and keeps it through a new question', () => {
    let state = run([
      ask(),
      ...sse(eventsFor(RESPONSE_2)),
      {type: 'index_status_loaded', status: INDEX_STATUS_STALE},
    ]);
    expect(kindOf(state)).toBe('stale_index');
    expect(baseState(state.ui).kind).toBe('complete');
    state = run(
      [ask(QUESTION_1, 'req-2'), ...sse(eventsFor(RESPONSE_1))],
      state,
    );
    expect(kindOf(state)).toBe('stale_index');
    expect(baseState(state.ui).kind).toBe('partial_coverage');
    state = reducer(state, {type: 'index_status_loaded', status: INDEX_STATUS});
    expect(kindOf(state)).toBe('stale_index');
  });

  it('wraps network_offline over the last answer and unwraps on online', () => {
    let state = run([ask(), ...sse(eventsFor(RESPONSE_2)), {type: 'offline'}]);
    expect(kindOf(state)).toBe('network_offline');
    expect(currentRun(state.ui)?.final?.request_id).toBe(RESPONSE_2.request_id);
    expect(canAsk(state.ui)).toBe(false);
    expect(reducer(state, ask()).ui).toBe(state.ui);
    state = reducer(state, {type: 'online'});
    expect(kindOf(state)).toBe('complete');
  });

  it('covers all 11 states of table 14.6', () => {
    expect([...seen].sort()).toEqual(
      [
        'complete',
        'empty',
        'index_not_built',
        'loading',
        'network_offline',
        'out_of_scope',
        'partial_coverage',
        'provider_down',
        'rate_limited',
        'stale_index',
        'streaming',
      ].sort(),
    );
  });
});

describe('reducer edge cases', () => {
  it('ignores events when no question is in flight', () => {
    const event: SseEvent = {event: 'answer_delta', data: {text: 'x'}};
    expect(reducer(initialState, {type: 'sse', event})).toBe(initialState);
  });

  it('ends in provider_down when done arrives before final', () => {
    const state = run([
      ask(),
      ...sse(eventsFor(RESPONSE_2).slice(0, 4)),
      ...sse([{event: 'done', data: null}]),
    ]);
    expect(state.ui.kind).toBe('provider_down');
  });

  it('marks the token rejected on 401 and drops the question', () => {
    const state = run([
      ask(),
      {
        type: 'http_error',
        status: 401,
        error: {code: 'unauthorized', message: 'no token'},
      },
    ]);
    expect(state.ui.kind).toBe('empty');
    expect(state.service.tokenRejected).toBe(true);
    expect(reducer(state, {type: 'token_set'}).service.tokenRejected).toBe(
      false,
    );
  });

  it('keeps the arrival order of the steps through final', () => {
    const events = eventsFor(RESPONSE_2);
    const [meta, analysis, retrieval] = events;
    if (
      meta === undefined ||
      analysis === undefined ||
      retrieval === undefined
    ) {
      throw new Error('fixture');
    }
    const state = run([ask(), ...sse([meta, retrieval, ...events.slice(3)])]);
    expect(currentRun(state.ui)?.stepsLit).toEqual([
      'understanding',
      'model',
      'retrieval',
    ]);
  });

  it('settles a stored result with its stored question', () => {
    const state = reducer(initialState, {
      type: 'result_loaded',
      result: RESPONSE_2,
      question: 'Q2?',
    });
    expect(currentRun(state.ui)?.question).toBe('Q2?');
  });

  it('settles a stored result after a refresh (E-F-04)', () => {
    const state = reducer(initialState, {
      type: 'result_loaded',
      result: RESPONSE_2,
    });
    expect(state.ui.kind).toBe('complete');
    expect(currentRun(state.ui)?.requestId).toBe(RESPONSE_2.request_id);
  });

  it('turns a broken stream into provider_down', () => {
    const state = run([ask(), {type: 'stream_failed', message: 'broken'}]);
    expect(state.ui.kind).toBe('provider_down');
  });

  it('reports a red dot when the service is unreachable', () => {
    expect(health(reducer(initialState, {type: 'service_unreachable'}))).toBe(
      'red',
    );
  });
});
