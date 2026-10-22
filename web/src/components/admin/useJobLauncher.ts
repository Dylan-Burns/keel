import {useCallback, useState} from 'react';

import {submitJob} from '../../api/admin';
import {ApiError} from '../../api/client';
import type {Job, JobRequest} from '../../api/types';

/** The state of a job the page asked for. */
export type LaunchState =
  | {readonly kind: 'idle'}
  | {readonly kind: 'sending'}
  | {
      readonly kind: 'started';
      readonly job: Job;
      readonly warnings: readonly string[];
    }
  | {
      readonly kind: 'busy';
      readonly jobId: string | null;
      readonly message: string;
    }
  | {readonly kind: 'failed'; readonly message: string};

/**
 * The page text of a refused job.
 *
 * @param error The error of `POST /api/admin/jobs`.
 * @return The launch state.
 */
export function refusal(error: unknown): LaunchState {
  if (!(error instanceof ApiError)) {
    return {kind: 'failed', message: 'The job could not be sent.'};
  }
  if (error.status === 409 && error.code === 'job_running') {
    const jobId = error.detail?.['job_id'];
    return {
      kind: 'busy',
      jobId: typeof jobId === 'string' ? jobId : null,
      message: error.message,
    };
  }
  if (error.status === 403) {
    return {kind: 'failed', message: 'Only an admin can run this job.'};
  }
  if (error.code === 'confirm_required' || error.code === 'confirm_mismatch') {
    const expected = error.detail?.['confirm'];
    return {
      kind: 'failed',
      message: `The confirmation did not match: the job needs "${String(expected)}".`,
    };
  }
  if (error.code === 'invalid_params') {
    const fields = error.detail?.['fields'];
    const named = Array.isArray(fields) ? ` (${fields.join(', ')})` : '';
    return {kind: 'failed', message: `${error.message}${named}`};
  }
  return {kind: 'failed', message: error.message};
}

/** The launcher of 1 job form. */
export interface JobLauncher {
  readonly state: LaunchState;
  readonly launch: (request: JobRequest) => void;
  readonly reset: () => void;
}

/**
 * Sends a job and keeps its state: the queued job, a 409 with the job
 * that holds the slot, or the error.
 *
 * @return The state and the actions.
 */
export function useJobLauncher(): JobLauncher {
  const [state, setState] = useState<LaunchState>({kind: 'idle'});
  const launch = useCallback((request: JobRequest): void => {
    setState({kind: 'sending'});
    submitJob(request)
      .then(sent =>
        setState({kind: 'started', job: sent.job, warnings: sent.warnings}),
      )
      .catch((error: unknown) => setState(refusal(error)));
  }, []);
  const reset = useCallback(() => setState({kind: 'idle'}), []);
  return {state, launch, reset};
}
