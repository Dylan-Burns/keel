import type {JSX} from 'react';

import type {JobStatus} from '../../api/types';

const TONE: Readonly<Record<JobStatus, string>> = {
  queued: 'tag-warn',
  running: 'tag-accent',
  succeeded: 'tag-up',
  failed: 'tag-down',
  cancelled: '',
};

/** Props of JobStatusTag. */
export interface JobStatusTagProps {
  readonly status: JobStatus;
}

/**
 * The status of a job as a tag: amber queued, blue running, green
 * succeeded, red failed, grey cancelled. The word carries the meaning, the
 * color repeats it.
 *
 * @param props The props.
 * @return The tag.
 */
export function JobStatusTag({status}: JobStatusTagProps): JSX.Element {
  return (
    <span className={`tag ${TONE[status]}`} data-testid="job-status">
      {status}
    </span>
  );
}
