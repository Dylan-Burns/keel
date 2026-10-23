import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import type {Job} from '../../api/types';
import {countsText, overallOf, stepsOf} from '../../lib/jobSteps';
import {jobBar, pickTransition} from '../../motion/presets';

/** Props of JobProgress. */
export interface JobProgressProps {
  readonly job: Job;
}

/**
 * The words of the overall progress of a job with steps: `step 4 of 11`,
 * `11 of 11 steps`, or `failed at step 6 of 11`.
 *
 * @param job The job.
 * @return The text.
 */
export function stepWords(job: Job): string {
  const overall = overallOf(job);
  const {stepNumber, stepCount} = overall;
  if (job.status === 'failed' && stepNumber > 0) {
    return `failed at step ${stepNumber} of ${stepCount}`;
  }
  if (job.status === 'succeeded') {
    return `${stepCount} of ${stepCount} steps`;
  }
  if (job.status === 'queued' || job.status === 'cancelled') {
    return `${stepCount} steps`;
  }
  return stepNumber > 0
    ? `step ${stepNumber} of ${stepCount}`
    : `${stepCount} steps`;
}

/**
 * The progress bar of a job. With steps: the ended steps plus the running
 * step's own counts, as a percent, with `step N of M` and the running step's
 * name. Without steps (a job recorded before them): the done of total, else
 * the step count.
 *
 * @param props The props.
 * @return The bar.
 */
export function JobProgress({job}: JobProgressProps): JSX.Element {
  const reduced = useReducedMotion();
  const stepped = stepsOf(job).length > 0;
  const {done, total} = job.progress ?? {done: 0, total: null};
  const finished = job.status === 'succeeded';
  const overall = overallOf(job);
  const ratio = stepped
    ? overall.ratio
    : total !== null && total > 0
      ? Math.min(1, done / total)
      : finished
        ? 1
        : 0;
  const percent = stepped ? overall.percent : Math.round(ratio * 100);
  const label = stepped
    ? `${stepWords(job)} · ${percent}%`
    : total !== null
      ? `${done} of ${total}`
      : done > 0
        ? `${done} steps`
        : '';
  const counts = countsText(overall.current?.progress ?? null);
  const phase =
    stepped && job.status === 'running' && overall.current !== null
      ? counts === ''
        ? overall.current.name
        : `${overall.current.name} · ${counts}`
      : job.phase;
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline gap-2 font-mono text-[11.5px]">
        <span className="min-w-0 truncate text-ink" data-testid="job-phase">
          {phase}
        </span>
        <span
          className="num ml-auto shrink-0 text-muted"
          data-testid="job-progress"
        >
          {label}
        </span>
      </div>
      <div
        className="meter h-1.5"
        role="progressbar"
        aria-label="Job progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={label || undefined}
      >
        <motion.div
          className={`origin-left ${
            job.status === 'failed'
              ? 'bg-down'
              : finished
                ? 'bg-up'
                : 'bg-accent'
          }`}
          initial={false}
          animate={{scaleX: ratio}}
          transition={pickTransition(jobBar, reduced)}
          style={{width: '100%'}}
        />
      </div>
    </div>
  );
}
