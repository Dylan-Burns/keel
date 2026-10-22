/**
 * Runs built through the real reducer, for the component tests.
 */
import type {AskResponse} from '../api/types';
import type {Run} from '../state';
import {currentRun, initialState, reducer} from '../state';
import {eventsFor} from './fixtures';

/**
 * The run after the first events of a recorded answer.
 *
 * @param response The recorded final response.
 * @param eventCount How many events to apply; all of them by default.
 * @return The run.
 */
export function runOf(response: AskResponse, eventCount = 1000): Run {
  let state = reducer(initialState, {
    type: 'ask',
    question: 'Q?',
    requestId: response.request_id,
  });
  for (const event of eventsFor(response).slice(0, eventCount)) {
    state = reducer(state, {type: 'sse', event});
  }
  const run = currentRun(state.ui);
  if (run === null) {
    throw new Error('the events left no run');
  }
  return run;
}
