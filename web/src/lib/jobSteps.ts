/**
 * The arithmetic of the job step view: the overall progress, the step
 * counts, and the durations. Pure functions, so the components stay thin.
 */
import type {Job, JobStep, StepProgress} from '../api/types';

/** The step statuses that end a step. */
const ENDED: ReadonlySet<string> = new Set(['succeeded', 'failed', 'skipped']);

/** The overall progress of a job with steps. */
export interface Overall {
  /** 0 to 1. */
  readonly ratio: number;
  /** 0 to 100, rounded down so 100 means every step ended. */
  readonly percent: number;
  /** The 1-based number of the step shown, or 0 before the first. */
  readonly stepNumber: number;
  readonly stepCount: number;
  /** The running step, else the failed one, else null. */
  readonly current: JobStep | null;
}

/**
 * The steps of a job; empty for a job recorded without steps.
 *
 * @param job The job.
 * @return The steps.
 */
export function stepsOf(job: Job): readonly JobStep[] {
  return job.steps ?? [];
}

/**
 * The fraction of a step's counts, or null when the total is unknown.
 *
 * @param progress The step counts.
 * @return 0 to 1, or null.
 */
export function stepRatio(progress: StepProgress | null): number | null {
  if (progress === null || progress.total === null || progress.total <= 0) {
    return null;
  }
  return Math.min(1, Math.max(0, progress.done / progress.total));
}

/**
 * The overall progress: the ended steps plus the running step's own
 * fraction, over all steps.
 *
 * @param job The job.
 * @return The ratio, the percent, and the step shown.
 */
export function overallOf(job: Job): Overall {
  const steps = stepsOf(job);
  const count = steps.length;
  const ended = steps.filter(step => ENDED.has(step.status)).length;
  const runningIndex = steps.findIndex(step => step.status === 'running');
  const failedIndex = steps.findIndex(step => step.status === 'failed');
  const running = runningIndex >= 0 ? steps[runningIndex] : undefined;
  const partial = running ? (stepRatio(running.progress) ?? 0) : 0;
  const ratio =
    count === 0
      ? job.status === 'succeeded'
        ? 1
        : 0
      : Math.min(1, (ended + partial) / count);
  const shownIndex =
    runningIndex >= 0
      ? runningIndex
      : failedIndex >= 0
        ? failedIndex
        : job.status === 'succeeded'
          ? count - 1
          : -1;
  const current =
    runningIndex >= 0
      ? (steps[runningIndex] ?? null)
      : failedIndex >= 0
        ? (steps[failedIndex] ?? null)
        : null;
  return {
    ratio,
    percent: Math.floor(ratio * 100),
    stepNumber: shownIndex + 1,
    stepCount: count,
    current,
  };
}

/**
 * The counts of a step as words: `1,240 of 3,400 chunks`.
 *
 * @param progress The step counts.
 * @return The text, or an empty string with no counts.
 */
export function countsText(progress: StepProgress | null): string {
  if (progress === null) {
    return '';
  }
  const unit = progress.unit ? ` ${progress.unit}` : '';
  const done = progress.done.toLocaleString('en-US');
  if (progress.total === null) {
    return `${done}${unit}`;
  }
  return `${done} of ${progress.total.toLocaleString('en-US')}${unit}`;
}

/**
 * The seconds between 2 ISO times, or from a start to now.
 *
 * @param start The start time, or null.
 * @param end The end time, or null for a step that still runs.
 * @param now The clock in milliseconds, for a running step.
 * @return The whole seconds, or null without a valid start.
 */
export function elapsedSeconds(
  start: string | null,
  end: string | null,
  now: number,
): number | null {
  if (start === null) {
    return null;
  }
  const from = Date.parse(start);
  const to = end === null ? now : Date.parse(end);
  if (Number.isNaN(from) || Number.isNaN(to)) {
    return null;
  }
  return Math.max(0, Math.floor((to - from) / 1000));
}

/**
 * A duration as the CI page shows it: `0s`, `42s`, `3m 05s`, `1h 02m`.
 *
 * @param seconds The whole seconds, or null.
 * @return The text, or an empty string for null.
 */
export function durationText(seconds: number | null): string {
  if (seconds === null) {
    return '';
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`;
  }
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, '0')}m`;
}
