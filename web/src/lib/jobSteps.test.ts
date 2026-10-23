import {describe, expect, it} from 'vitest';

import type {JobStep} from '../api/types';
import {job} from '../testing/admin';
import {
  countsText,
  durationText,
  elapsedSeconds,
  overallOf,
  stepRatio,
} from './jobSteps';

function step(fields: Partial<JobStep> = {}): JobStep {
  return {
    key: 'parse',
    name: 'Parse',
    status: 'pending',
    started_at: null,
    finished_at: null,
    progress: null,
    log: [],
    ...fields,
  };
}

describe('jobSteps', () => {
  it('counts the ended steps and the running fraction', () => {
    const running = job({
      status: 'running',
      steps: [
        step({key: 'a', status: 'succeeded'}),
        step({key: 'b', status: 'skipped'}),
        step({
          key: 'c',
          name: 'Embed',
          status: 'running',
          progress: {done: 50, total: 100, unit: 'chunks'},
        }),
        step({key: 'd'}),
      ],
    });
    const overall = overallOf(running);
    expect(overall.ratio).toBeCloseTo(2.5 / 4);
    expect(overall.percent).toBe(62);
    expect(overall.stepNumber).toBe(3);
    expect(overall.stepCount).toBe(4);
    expect(overall.current?.name).toBe('Embed');
  });

  it('points at the failed step and finishes at 100', () => {
    const failed = overallOf(
      job({
        status: 'failed',
        steps: [
          step({key: 'a', status: 'succeeded'}),
          step({key: 'b', status: 'failed'}),
          step({key: 'c', status: 'skipped'}),
        ],
      }),
    );
    expect(failed.stepNumber).toBe(2);
    expect(failed.current?.key).toBe('b');
    expect(failed.percent).toBe(100);
    const none = overallOf(job({status: 'succeeded', steps: []}));
    expect(none.ratio).toBe(1);
    expect(overallOf(job({status: 'queued'})).stepNumber).toBe(0);
  });

  it('writes the counts, the ratio, and the durations', () => {
    expect(countsText({done: 1240, total: 3400, unit: 'chunks'})).toBe(
      '1,240 of 3,400 chunks',
    );
    expect(countsText({done: 3, total: null, unit: ''})).toBe('3');
    expect(countsText(null)).toBe('');
    expect(stepRatio({done: 5, total: 0, unit: ''})).toBeNull();
    expect(stepRatio({done: 9, total: 4, unit: ''})).toBe(1);
    expect(durationText(null)).toBe('');
    expect(durationText(7)).toBe('7s');
    expect(durationText(185)).toBe('3m 05s');
    expect(durationText(3720)).toBe('1h 02m');
    const start = '2026-10-23T10:00:00+00:00';
    expect(elapsedSeconds(start, '2026-10-23T10:00:42+00:00', 0)).toBe(42);
    expect(elapsedSeconds(start, null, Date.parse(start) + 5500)).toBe(5);
    expect(elapsedSeconds(start, null, 0)).toBe(0);
    expect(elapsedSeconds(null, null, 0)).toBeNull();
    expect(elapsedSeconds('not a time', null, 0)).toBeNull();
  });
});
