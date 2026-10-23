import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import type {JobStep} from '../../api/types';
import {
  countsText,
  durationText,
  elapsedSeconds,
  stepRatio,
} from '../../lib/jobSteps';
import {jobBar, jobSteps, pick, pickTransition} from '../../motion/presets';
import {JobStepIcon} from './JobStepIcon';
import {JobStepLog} from './JobStepLog';

/** Props of JobStepRow. */
export interface JobStepRowProps {
  readonly jobId: string;
  readonly index: number;
  readonly step: JobStep;
  /** True when the log is open. */
  readonly open: boolean;
  /** Opens or closes the log. */
  readonly onToggle: (key: string) => void;
  /** The clock in milliseconds, for the duration of a running step. */
  readonly now: number;
}

const NAME_TONE: Readonly<Record<JobStep['status'], string>> = {
  pending: 'text-muted',
  running: 'font-semibold text-ink',
  succeeded: 'text-ink',
  failed: 'font-semibold text-down',
  skipped: 'text-muted',
};

/**
 * 1 step of a job: the status mark, the name, the duration (it ticks while
 * the step runs), the counts the step reported with a thin bar, and a
 * button that opens the step log. The parent decides when the log is open.
 *
 * @param props The props.
 * @return The row.
 */
export function JobStepRow({
  jobId,
  index,
  step,
  open,
  onToggle,
  now,
}: JobStepRowProps): JSX.Element {
  const reduced = useReducedMotion();
  const logId = `job-${jobId}-step-${index}`;
  const seconds = elapsedSeconds(
    step.started_at,
    step.status === 'running' ? null : step.finished_at,
    now,
  );
  const counts = countsText(step.progress);
  const ratio = stepRatio(step.progress);
  const running = step.status === 'running';
  return (
    <li
      className={`border-b border-line last:border-b-0 ${running ? 'bg-raised' : ''}`}
      data-testid="job-step"
      data-key={step.key}
      data-status={step.status}
      data-open={open}
    >
      <button
        type="button"
        className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left hover:bg-raised focus-visible:outline-offset-[-2px]"
        aria-expanded={open}
        aria-controls={logId}
        onClick={() => onToggle(step.key)}
        data-testid="job-step-toggle"
      >
        <svg
          viewBox="0 0 10 10"
          className={`h-2.5 w-2.5 shrink-0 text-muted ${open ? 'rotate-90' : ''}`}
          aria-hidden="true"
        >
          <path d="M3 1.5 7 5 3 8.5" fill="none" stroke="currentColor" />
        </svg>
        <JobStepIcon status={step.status} />
        <span className="min-w-0 flex-1">
          <span
            className={`block truncate text-[12.5px] ${NAME_TONE[step.status]}`}
            data-testid="job-step-name"
          >
            {step.name}
          </span>
          {counts !== '' && (
            <span
              className="num mt-0.5 flex items-center gap-2 text-[11px] text-ink-2"
              data-testid="job-step-counts"
            >
              <span className="truncate">{counts}</span>
              {ratio !== null && running && (
                <span
                  className="meter hidden w-24 shrink-0 sm:block"
                  aria-hidden="true"
                >
                  <motion.span
                    className="block origin-left bg-accent"
                    initial={false}
                    animate={{scaleX: ratio}}
                    transition={pickTransition(jobBar, reduced)}
                  />
                </span>
              )}
            </span>
          )}
        </span>
        <span
          className="num shrink-0 text-[11px] text-muted"
          data-testid="job-step-duration"
        >
          {step.status === 'skipped' ? 'skipped' : durationText(seconds)}
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="log"
            className="overflow-hidden"
            variants={pick(jobSteps.log, reduced)}
            initial="hidden"
            animate="visible"
            exit="exit"
          >
            <JobStepLog
              id={logId}
              name={step.name}
              lines={step.log}
              live={running}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}
