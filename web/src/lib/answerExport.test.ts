import {describe, expect, it} from 'vitest';

import {currentRun, initialState, reducer} from '../state';
import {RESPONSE_1, eventsFor} from '../testing/fixtures';
import {answerToJson, answerToMarkdown, partialHeader} from './answerExport';

function runAfter(eventCount: number) {
  const events = eventsFor(RESPONSE_1);
  let state = reducer(initialState, {
    type: 'ask',
    question: 'Q?',
    requestId: 'req-x',
  });
  for (const event of events.slice(0, eventCount)) {
    state = reducer(state, {type: 'sse', event});
  }
  const run = currentRun(state.ui);
  if (run === null) {
    throw new Error('no run');
  }
  return run;
}

describe('answerToMarkdown', () => {
  it('test_copy_partial_header: a copy during the stream says partial with the request ID', () => {
    const run = runAfter(5);
    const text = answerToMarkdown(run);
    expect(text.split('\n')[0]).toBe(partialHeader(RESPONSE_1.request_id));
    expect(text).toContain('Partial answer');
    expect(text).toContain(RESPONSE_1.request_id);
  });

  it('a complete copy has no partial header and lists the sources', () => {
    const run = runAfter(100);
    const text = answerToMarkdown(run);
    expect(text).not.toContain('Partial answer');
    expect(text).toContain('## Sources');
    expect(text).toContain('(unverified)');
    expect(text).toContain('| Company | Main risk |');
  });

  it('exports the final response as JSON, or the parts received', () => {
    expect(JSON.parse(answerToJson(runAfter(100)))).toEqual(RESPONSE_1);
    expect(JSON.parse(answerToJson(runAfter(4)))).toMatchObject({
      partial: true,
    });
  });
});
