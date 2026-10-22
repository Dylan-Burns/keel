/**
 * The 11 UI states of chapter 14.6 as 1 union type, and the 1 reducer that
 * moves between them on the server-sent events and the HTTP results.
 *
 * 2 states are overlays: `stale_index` and `network_offline` wrap the state
 * underneath (`under`), so the last answer stays on screen while the banner
 * shows. Every other action passes through an overlay to the state below.
 */
import type {
  AnalysisSummary,
  AskResponse,
  CompanyFindings,
  CoverageResponse,
  ErrorEvent,
  IndexStatusResponse,
  MetaEvent,
  ReadyResponse,
  RetrievalSummary,
  SseEvent,
} from './api/types';

/** The names of the 11 states of table 14.6. */
export type UiStateKind = UiState['kind'];

/** The 3 pipeline steps of the progress line, in order. */
export type PipelineStep = 'understanding' | 'retrieval' | 'model';

/** The pipeline steps in display order. */
export const PIPELINE_STEPS: readonly PipelineStep[] = [
  'understanding',
  'retrieval',
  'model',
];

/** Everything the page knows about 1 question and its answer. */
export interface Run {
  readonly question: string;
  readonly requestId: string;
  /** The steps lit so far, in the order their events arrived. */
  readonly stepsLit: readonly PipelineStep[];
  readonly meta: MetaEvent | null;
  readonly analysis: AnalysisSummary | null;
  readonly retrieval: RetrievalSummary | null;
  /** The `answer_delta` texts, in order; their join is the answer so far. */
  readonly deltas: readonly string[];
  readonly findings: readonly CompanyFindings[];
  readonly final: AskResponse | null;
}

/** The page loads: the question area, the examples, the coverage summary. */
export interface EmptyState {
  readonly kind: 'empty';
}

/** The question is sent: the 3 progress steps light up. */
export interface LoadingState {
  readonly kind: 'loading';
  readonly run: Run;
}

/** The first `answer_delta` arrived: the answer grows in place. */
export interface StreamingState {
  readonly kind: 'streaming';
  readonly run: Run;
}

/** The `final` event arrived with full coverage. */
export interface CompleteState {
  readonly kind: 'complete';
  readonly run: Run;
}

/** A company is missing or a finding is unverified: the yellow banner. */
export interface PartialCoverageState {
  readonly kind: 'partial_coverage';
  readonly run: Run;
  readonly companiesMissing: readonly string[];
  readonly unverifiedFindings: number;
}

/** A refusal or the no-call response: the gray card. */
export interface OutOfScopeState {
  readonly kind: 'out_of_scope';
  readonly run: Run;
  readonly reason: string;
}

/** HTTP 429: the card with the countdown; Ask stays off until it ends. */
export interface RateLimitedState {
  readonly kind: 'rate_limited';
  /** Seconds left of the wait. */
  readonly secondsLeft: number;
  /** The state to return to when the countdown ends. */
  readonly previous: UiState;
}

/** The provider is down or the answer is degraded: the red banner. */
export interface ProviderDownState {
  readonly kind: 'provider_down';
  /** The run with its retrieved chunks, or null before any question. */
  readonly run: Run | null;
  readonly code: string;
  readonly message: string;
}

/** `/api/ready` reports no index: the full-page card. */
export interface IndexNotBuiltState {
  readonly kind: 'index_not_built';
}

/** The corpus checksum does not match the index: the amber banner. */
export interface StaleIndexState {
  readonly kind: 'stale_index';
  readonly under: UiState;
}

/** The browser is offline: the red banner over the last answer. */
export interface NetworkOfflineState {
  readonly kind: 'network_offline';
  readonly under: UiState;
}

/** The 11 UI states of table 14.6. */
export type UiState =
  | EmptyState
  | LoadingState
  | StreamingState
  | CompleteState
  | PartialCoverageState
  | OutOfScopeState
  | RateLimitedState
  | ProviderDownState
  | IndexNotBuiltState
  | StaleIndexState
  | NetworkOfflineState;

/** The health dot colors of the top bar. */
export type Health = 'green' | 'amber' | 'red' | 'unknown';

/** The service facts the page loads at start. */
export interface ServiceInfo {
  readonly ready: ReadyResponse | null;
  readonly reachable: boolean | null;
  readonly coverage: CoverageResponse | null;
  readonly indexStatus: IndexStatusResponse | null;
  /** True after a 401: the token field asks for a new token. */
  readonly tokenRejected: boolean;
}

/** The page state: the UI state and the service facts. */
export interface AppState {
  readonly ui: UiState;
  readonly service: ServiceInfo;
}

/** The actions of the reducer. */
export type Action =
  | {readonly type: 'ready_loaded'; readonly ready: ReadyResponse}
  | {readonly type: 'service_unreachable'}
  | {readonly type: 'index_status_loaded'; readonly status: IndexStatusResponse}
  | {readonly type: 'coverage_loaded'; readonly coverage: CoverageResponse}
  | {readonly type: 'token_rejected'}
  | {readonly type: 'token_set'}
  | {
      readonly type: 'ask';
      readonly question: string;
      readonly requestId: string;
    }
  | {readonly type: 'sse'; readonly event: SseEvent}
  | {
      readonly type: 'result_loaded';
      readonly result: AskResponse;
      /** The question stored with the request ID, when known. */
      readonly question?: string | null;
    }
  | {
      readonly type: 'http_error';
      readonly status: number;
      readonly error: ErrorEvent;
    }
  | {readonly type: 'stream_failed'; readonly message: string}
  | {readonly type: 'rate_limit_tick'}
  | {readonly type: 'offline'}
  | {readonly type: 'online'};

/** The state of a page that just loaded. */
export const initialState: AppState = {
  ui: {kind: 'empty'},
  service: {
    ready: null,
    reachable: null,
    coverage: null,
    indexStatus: null,
    tokenRejected: false,
  },
};

/**
 * Makes the run of a new question.
 *
 * @param question The question.
 * @param requestId The idempotency key.
 * @return The run with nothing received yet.
 */
export function newRun(question: string, requestId: string): Run {
  return {
    question,
    requestId,
    stepsLit: [],
    meta: null,
    analysis: null,
    retrieval: null,
    deltas: [],
    findings: [],
    final: null,
  };
}

/**
 * The state under the overlays (`stale_index`, `network_offline`).
 *
 * @param ui A state.
 * @return The first state that is not an overlay.
 */
export function baseState(ui: UiState): UiState {
  let state = ui;
  while (state.kind === 'stale_index' || state.kind === 'network_offline') {
    state = state.under;
  }
  return state;
}

/**
 * True when an overlay of the given kind wraps the state.
 *
 * @param ui A state.
 * @param kind The overlay kind.
 * @return Whether the overlay is present.
 */
export function hasOverlay(
  ui: UiState,
  kind: 'stale_index' | 'network_offline',
): boolean {
  let state = ui;
  while (state.kind === 'stale_index' || state.kind === 'network_offline') {
    if (state.kind === kind) {
      return true;
    }
    state = state.under;
  }
  return false;
}

/**
 * The run that the page shows, from any state.
 *
 * @param ui A state.
 * @return The run, or null.
 */
export function currentRun(ui: UiState): Run | null {
  const base = baseState(ui);
  switch (base.kind) {
    case 'loading':
    case 'streaming':
    case 'complete':
    case 'partial_coverage':
    case 'out_of_scope':
      return base.run;
    case 'provider_down':
      return base.run;
    case 'rate_limited':
      return currentRun(base.previous);
    default:
      return null;
  }
}

/**
 * The answer text so far: the final answer, else the joined deltas.
 *
 * @param run The run.
 * @return The direct answer text.
 */
export function answerText(run: Run): string {
  return run.final?.answer.direct_answer ?? run.deltas.join('');
}

/**
 * True while an answer is in flight (loading or streaming).
 *
 * @param ui A state.
 * @return Whether a question is in flight.
 */
export function isBusy(ui: UiState): boolean {
  const kind = baseState(ui).kind;
  return kind === 'loading' || kind === 'streaming';
}

/**
 * True when the Ask button is on.
 *
 * @param ui A state.
 * @return Whether the user may send a question.
 */
export function canAsk(ui: UiState): boolean {
  if (hasOverlay(ui, 'network_offline')) {
    return false;
  }
  const kind = baseState(ui).kind;
  return !isBusy(ui) && kind !== 'rate_limited' && kind !== 'index_not_built';
}

/**
 * The health dot color: green when ready, amber when degraded or stale,
 * red when the service is down or not ready.
 *
 * @param state The page state.
 * @return The color.
 */
export function health(state: AppState): Health {
  const {ready, reachable} = state.service;
  if (reachable === false || hasOverlay(state.ui, 'network_offline')) {
    return 'red';
  }
  if (ready === null) {
    return 'unknown';
  }
  if (!ready.ready) {
    return 'red';
  }
  if (
    !ready.checks.provider_key ||
    hasOverlay(state.ui, 'stale_index') ||
    baseState(state.ui).kind === 'provider_down'
  ) {
    return 'amber';
  }
  return 'green';
}

function lightStep(run: Run, step: PipelineStep): Run {
  return run.stepsLit.includes(step)
    ? run
    : {...run, stepsLit: [...run.stepsLit, step]};
}

/**
 * The end state of a run with its final answer.
 *
 * @param run The run with `final` set.
 * @param result The final answer.
 * @return The complete, partial coverage, out of scope, or provider down state.
 */
function settle(run: Run, result: AskResponse): UiState {
  const done: Run = {
    ...run,
    // Keep the arrival order; add only the steps whose events never came.
    stepsLit: [
      ...run.stepsLit,
      ...PIPELINE_STEPS.filter(step => !run.stepsLit.includes(step)),
    ],
    analysis: result.analysis,
    retrieval: result.retrieval,
    findings: result.answer.company_findings,
    final: result,
  };
  if (result.answer.refusal !== null) {
    return {
      kind: 'out_of_scope',
      run: done,
      reason: result.answer.refusal.reason,
    };
  }
  if (result.meta.degraded) {
    return {
      kind: 'provider_down',
      run: done,
      code: 'degraded',
      message: 'The model is unavailable. The retrieved chunks are below.',
    };
  }
  const coverage = result.answer.coverage;
  const missing =
    'companies_missing' in coverage ? coverage.companies_missing : [];
  const unverified = result.answer.company_findings.reduce(
    (count, company) =>
      count + company.findings.filter(f => f.unverified === true).length,
    0,
  );
  if (missing.length > 0 || unverified > 0) {
    return {
      kind: 'partial_coverage',
      run: done,
      companiesMissing: missing,
      unverifiedFindings: unverified,
    };
  }
  return {kind: 'complete', run: done};
}

function failRun(run: Run | null, error: ErrorEvent): UiState {
  if (error.code === 'rate_limited') {
    return {
      kind: 'rate_limited',
      secondsLeft: Math.max(1, Math.ceil(error.retry_after ?? 60)),
      // The previous answer comes back when the countdown ends.
      previous: run?.final ? settle(run, run.final) : {kind: 'empty'},
    };
  }
  return {kind: 'provider_down', run, code: error.code, message: error.message};
}

/**
 * Applies 1 server-sent event to the in-flight run.
 *
 * @param ui The base state (not an overlay).
 * @param event The event.
 * @return The next base state.
 */
function onEvent(ui: UiState, event: SseEvent): UiState {
  if (ui.kind !== 'loading' && ui.kind !== 'streaming') {
    return ui;
  }
  const run = ui.run;
  switch (event.event) {
    case 'meta':
      return {
        kind: ui.kind,
        run: {...lightStep(run, 'understanding'), meta: event.data},
      };
    case 'analysis':
      return {
        kind: ui.kind,
        run: {...lightStep(run, 'retrieval'), analysis: event.data},
      };
    case 'retrieval':
      return {
        kind: ui.kind,
        run: {...lightStep(run, 'model'), retrieval: event.data},
      };
    case 'answer_delta':
      return {
        kind: 'streaming',
        run: {...run, deltas: [...run.deltas, event.data.text]},
      };
    case 'findings':
      return {
        kind: ui.kind,
        run: {...run, findings: [...run.findings, event.data]},
      };
    case 'final':
      return settle(run, event.data);
    case 'error':
      return failRun(run, event.data);
    case 'done':
      return {
        kind: 'provider_down',
        run,
        code: 'stream_incomplete',
        message: 'The stream ended before the answer was complete.',
      };
  }
}

/**
 * Applies an action to the base state (the overlays are handled outside).
 *
 * @param ui The base state.
 * @param action The action.
 * @return The next base state.
 */
function reduceBase(ui: UiState, action: Action): UiState {
  switch (action.type) {
    case 'ready_loaded':
      if (!action.ready.ready && !action.ready.checks.index_loaded) {
        return {kind: 'index_not_built'};
      }
      if (ui.kind === 'index_not_built') {
        return {kind: 'empty'};
      }
      if (!action.ready.checks.provider_key && ui.kind === 'empty') {
        return {
          kind: 'provider_down',
          run: null,
          code: 'provider_key_missing',
          message:
            'The model is unavailable: no provider key. Cached answers still work.',
        };
      }
      return ui;
    case 'ask':
      if (!canAsk(ui)) {
        return ui;
      }
      return {kind: 'loading', run: newRun(action.question, action.requestId)};
    case 'sse':
      return onEvent(ui, action.event);
    case 'result_loaded': {
      const previous = currentRun(ui);
      const run =
        previous !== null && previous.requestId === action.result.request_id
          ? previous
          : // An empty question (the /a/ route) turns Retry off.
            newRun(action.question ?? '', action.result.request_id);
      return settle(run, action.result);
    }
    case 'http_error': {
      const run = currentRun(ui);
      if (action.status === 429) {
        return failRun(run, {...action.error, code: 'rate_limited'});
      }
      if (action.status === 401) {
        // The token field asks for a new token; the question is not sent.
        return isBusy(ui) ? {kind: 'empty'} : ui;
      }
      return failRun(isBusy(ui) ? run : null, action.error);
    }
    case 'stream_failed':
      if (!isBusy(ui)) {
        return ui;
      }
      return {
        kind: 'provider_down',
        run: currentRun(ui),
        code: 'stream_failed',
        message: action.message,
      };
    case 'rate_limit_tick':
      if (ui.kind !== 'rate_limited') {
        return ui;
      }
      return ui.secondsLeft <= 1
        ? ui.previous
        : {...ui, secondsLeft: ui.secondsLeft - 1};
    default:
      return ui;
  }
}

/**
 * Rebuilds the overlays around a new base state.
 *
 * @param ui The current state with its overlays.
 * @param base The new base state.
 * @return The new state with the same overlays.
 */
function rewrap(ui: UiState, base: UiState): UiState {
  if (ui.kind === 'stale_index' || ui.kind === 'network_offline') {
    return {kind: ui.kind, under: rewrap(ui.under, base)};
  }
  return base;
}

function removeOverlay(ui: UiState, kind: 'network_offline'): UiState {
  if (ui.kind === kind) {
    return removeOverlay(ui.under, kind);
  }
  if (ui.kind === 'stale_index') {
    return {kind: 'stale_index', under: removeOverlay(ui.under, kind)};
  }
  return ui;
}

function reduceUi(ui: UiState, action: Action): UiState {
  switch (action.type) {
    case 'offline':
      return hasOverlay(ui, 'network_offline')
        ? ui
        : {kind: 'network_offline', under: ui};
    case 'online':
      return removeOverlay(ui, 'network_offline');
    case 'index_status_loaded':
      // The stale banner never leaves the screen on its own (14.8).
      return action.status.corpus_checksum_match ||
        hasOverlay(ui, 'stale_index')
        ? ui
        : {kind: 'stale_index', under: ui};
    case 'ask':
      // The ask check reads the overlays, so it runs on the whole state.
      return canAsk(ui) ? rewrap(ui, reduceBase(baseState(ui), action)) : ui;
    default:
      return rewrap(ui, reduceBase(baseState(ui), action));
  }
}

function reduceService(service: ServiceInfo, action: Action): ServiceInfo {
  switch (action.type) {
    case 'ready_loaded':
      return {...service, ready: action.ready, reachable: true};
    case 'service_unreachable':
      return {...service, reachable: false};
    case 'index_status_loaded':
      return {...service, indexStatus: action.status};
    case 'coverage_loaded':
      return {...service, coverage: action.coverage, tokenRejected: false};
    case 'token_rejected':
      return {...service, tokenRejected: true};
    case 'token_set':
      return {...service, tokenRejected: false};
    case 'http_error':
      return action.status === 401
        ? {...service, tokenRejected: true}
        : service;
    default:
      return service;
  }
}

/**
 * The 1 reducer of the page.
 *
 * @param state The current state.
 * @param action The action.
 * @return The next state.
 */
export function reducer(state: AppState, action: Action): AppState {
  const ui = reduceUi(state.ui, action);
  const service = reduceService(state.service, action);
  return ui === state.ui && service === state.service ? state : {ui, service};
}
