import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import type {JobStepStatus} from '../../api/types';
import {jobSteps, pick} from '../../motion/presets';

/** Props of JobStepIcon. */
export interface JobStepIconProps {
  readonly status: JobStepStatus;
}

/** The words a screen reader hears for each status. */
export const STEP_STATUS_WORDS: Readonly<Record<JobStepStatus, string>> = {
  pending: 'pending',
  running: 'running',
  succeeded: 'succeeded',
  failed: 'failed',
  skipped: 'skipped',
};

/**
 * The status mark of 1 job step, as a CI run shows it: a hollow circle
 * pending, a turning dashed ring running, a green check succeeded, a red
 * cross failed, a struck grey circle skipped. The shape carries the
 * meaning, the color repeats it, and the word is there for screen readers.
 * The ring turns with the `jobSteps.spinner` preset and holds still under
 * reduced motion; a finished mark pops in once.
 *
 * @param props The props.
 * @return The icon.
 */
export function JobStepIcon({status}: JobStepIconProps): JSX.Element {
  const reduced = useReducedMotion();
  return (
    <span
      className="relative inline-flex h-4 w-4 shrink-0 items-center justify-center"
      data-testid="job-step-icon"
      data-status={status}
    >
      <span className="sr-only">{STEP_STATUS_WORDS[status]}</span>
      {status === 'running' ? (
        <motion.svg
          viewBox="0 0 16 16"
          className="h-4 w-4 text-accent"
          aria-hidden="true"
          variants={pick(jobSteps.spinner, reduced)}
          initial="idle"
          animate="spin"
        >
          <circle
            cx="8"
            cy="8"
            r="6"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeDasharray="3.6 1.112"
          />
          <circle cx="8" cy="8" r="2" fill="currentColor" />
        </motion.svg>
      ) : (
        <motion.svg
          key={status}
          viewBox="0 0 16 16"
          className={`h-4 w-4 ${TONE[status]}`}
          aria-hidden="true"
          variants={pick(jobSteps.icon, reduced)}
          initial={status === 'pending' ? false : 'hidden'}
          animate="visible"
        >
          {SHAPES[status]}
        </motion.svg>
      )}
    </span>
  );
}

const TONE: Readonly<Record<Exclude<JobStepStatus, 'running'>, string>> = {
  pending: 'text-muted',
  succeeded: 'text-up',
  failed: 'text-down',
  skipped: 'text-muted',
};

const SHAPES: Readonly<Record<Exclude<JobStepStatus, 'running'>, JSX.Element>> =
  {
    pending: (
      <circle
        cx="8"
        cy="8"
        r="6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    ),
    succeeded: (
      <>
        <circle cx="8" cy="8" r="7" fill="currentColor" />
        <path
          d="M4.8 8.3 7 10.4l4.2-4.6"
          fill="none"
          stroke="var(--k-panel)"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </>
    ),
    failed: (
      <>
        <circle cx="8" cy="8" r="7" fill="currentColor" />
        <path
          d="m5.6 5.6 4.8 4.8m0-4.8-4.8 4.8"
          fill="none"
          stroke="var(--k-panel)"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      </>
    ),
    skipped: (
      <>
        <circle
          cx="8"
          cy="8"
          r="6"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        <path
          d="m4 12 8-8"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </>
    ),
  };
