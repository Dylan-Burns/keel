import {useEffect, useRef, useState} from 'react';

import {fetchJob} from '../../api/admin';
import {ApiError} from '../../api/client';
import type {Job, JobStatus} from '../../api/types';

/** The poll interval of a running job (docs/API_ADMIN.md: 1 to 2 s). */
export const POLL_MS = 1500;

/** The statuses after which a job never changes. */
export const FINAL_STATUSES: ReadonlySet<JobStatus> = new Set<JobStatus>([
  'succeeded',
  'failed',
  'cancelled',
]);

/**
 * True when a job runs to no further change.
 *
 * @param job The job.
 * @return True for succeeded, failed, or cancelled.
 */
export function isFinal(job: Job): boolean {
  return FINAL_STATUSES.has(job.status);
}

/** The polled job and the last poll error. */
export interface JobPoll {
  readonly job: Job | null;
  readonly error: string | null;
  /** Replaces the job with a newer copy, such as a cancel response. */
  readonly replace: (job: Job) => void;
}

/**
 * Polls `GET /api/admin/jobs/{id}` every 1.5 s while the job is queued or
 * running, and stops at its final status, at a 401, 403, or 404, or when
 * the component unmounts. The parent keys the caller by the job ID.
 *
 * @param id The job ID.
 * @param initial The job record the submit response returned, if any.
 * @param onFinal Called once when the job reaches a final status.
 * @return The job, the error, and a setter.
 */
export function useJob(
  id: string,
  initial: Job | null = null,
  onFinal?: (job: Job) => void,
): JobPoll {
  const [job, setJob] = useState<Job | null>(initial);
  const [error, setError] = useState<string | null>(null);
  const finalRef = useRef(onFinal);
  const announced = useRef(initial !== null && isFinal(initial));
  useEffect(() => {
    finalRef.current = onFinal;
  });
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const poll = (): void => {
      fetchJob(id)
        .then(next => {
          if (cancelled) {
            return;
          }
          // A poll that left before a cancel must not undo it.
          setJob(current =>
            current !== null && isFinal(current) && !isFinal(next)
              ? current
              : next,
          );
          setError(null);
          if (isFinal(next)) {
            if (!announced.current) {
              announced.current = true;
              finalRef.current?.(next);
            }
            return;
          }
          timer = window.setTimeout(poll, POLL_MS);
        })
        .catch((failure: unknown) => {
          if (cancelled) {
            return;
          }
          if (
            failure instanceof ApiError &&
            [401, 403, 404].includes(failure.status)
          ) {
            setError(
              failure.status === 404
                ? 'No job with this ID.'
                : 'The job could not load with this token.',
            );
            return;
          }
          setError('The job status could not load; retrying.');
          timer = window.setTimeout(poll, POLL_MS * 2);
        });
    };
    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [id]);
  return {job, error, replace: setJob};
}
