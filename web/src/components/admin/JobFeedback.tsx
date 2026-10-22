import type {JSX} from 'react';

import type {Job} from '../../api/types';
import {jobPath} from '../../lib/links';
import {JobCard} from './JobCard';
import type {LaunchState} from './useJobLauncher';

/** Props of JobFeedback. */
export interface JobFeedbackProps {
  readonly state: LaunchState;
  /** Called once when the started job reaches a final status. */
  readonly onFinal?: (job: Job) => void;
}

/**
 * What became of a job the page sent: the live job card, the job that
 * holds the maintenance slot (HTTP 409, with a link), or the error.
 *
 * @param props The props.
 * @return The feedback, or nothing while idle.
 */
export function JobFeedback({
  state,
  onFinal,
}: JobFeedbackProps): JSX.Element | null {
  switch (state.kind) {
    case 'idle':
      return null;
    case 'sending':
      return (
        <p className="text-[12px] text-muted" role="status">
          Sending the job.
        </p>
      );
    case 'started':
      return (
        <JobCard
          key={state.job.id}
          id={state.job.id}
          initial={state.job}
          warnings={state.warnings}
          {...(onFinal === undefined ? {} : {onFinal})}
        />
      );
    case 'busy':
      return (
        <div
          className="notice notice-warn text-[13px]"
          role="alert"
          data-testid="job-busy"
        >
          <p className="font-semibold">Another job is running.</p>
          <p className="mt-1 text-ink-2">
            {state.message}.{' '}
            {state.jobId !== null ? (
              <a
                className="link"
                href={jobPath(state.jobId)}
                data-testid="job-busy-link"
              >
                Open the running job
              </a>
            ) : (
              'The first-start bootstrap or a nightly job holds the slot; try again when it ends.'
            )}
          </p>
        </div>
      );
    case 'failed':
      return (
        <p
          className="notice notice-down text-[13px]"
          role="alert"
          data-testid="job-failed"
        >
          {state.message}
        </p>
      );
  }
}
