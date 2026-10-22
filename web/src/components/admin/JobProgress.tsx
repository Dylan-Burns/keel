import type {JSX} from 'react';

import type {Job} from '../../api/types';

/** Props of JobProgress. */
export interface JobProgressProps {
  readonly job: Job;
}

/**
 * The progress bar of a job: a determinate bar with a known total, else
 * the step count.
 *
 * @param props The props.
 * @return The bar.
 */
export function JobProgress({job}: JobProgressProps): JSX.Element {
  const {done, total} = job.progress;
  const finished = job.status === 'succeeded';
  const ratio =
    total !== null && total > 0 ? Math.min(1, done / total) : finished ? 1 : 0;
  const label =
    total !== null ? `${done} of ${total}` : done > 0 ? `${done} steps` : '';
  return (
    <div className="space-y-1">
      <div className="flex items-baseline gap-2 font-mono text-[11.5px]">
        <span className="text-ink" data-testid="job-phase">
          {job.phase}
        </span>
        <span className="num ml-auto text-muted" data-testid="job-progress">
          {label}
        </span>
      </div>
      <div
        className="meter h-1.5"
        role="progressbar"
        aria-label="Job progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(ratio * 100)}
      >
        <div
          className={
            job.status === 'failed'
              ? 'bg-down'
              : finished
                ? 'bg-up'
                : 'bg-accent'
          }
          style={{width: `${Math.round(ratio * 100)}%`}}
        />
      </div>
    </div>
  );
}
