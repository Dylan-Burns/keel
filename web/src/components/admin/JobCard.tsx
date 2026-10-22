import type {JSX} from 'react';
import {useState} from 'react';

import {cancelJob} from '../../api/admin';
import {ApiError} from '../../api/client';
import type {Job} from '../../api/types';
import {scalar, when} from '../../lib/format';
import {jobPath} from '../../lib/links';
import {JobProgress} from './JobProgress';
import {JobResult} from './JobResult';
import {JobStatusTag} from './JobStatusTag';
import {isFinal, useJob} from './useJob';

/** Props of JobCard. */
export interface JobCardProps {
  /** The job ID; the parent keys the card by it. */
  readonly id: string;
  /** The record of the submit response, shown before the first poll. */
  readonly initial?: Job | null;
  /** Called once when the job reaches a final status. */
  readonly onFinal?: (job: Job) => void;
  /** Show the link to the job page (off on the job page itself). */
  readonly linkToJob?: boolean;
  /** The warnings of the submit response. */
  readonly warnings?: readonly string[];
}

/**
 * 1 admin job with live progress: it polls the job every 1.5 s while it is
 * queued or running and stops at its final status. It shows the kind, the
 * status, the phase, a progress bar, the times, the parameters, the error,
 * the result, and the log tail, and cancels a queued job. The log and the
 * result are JSX text nodes.
 *
 * @param props The props.
 * @return The card.
 */
export function JobCard({
  id,
  initial = null,
  onFinal,
  linkToJob = true,
  warnings = [],
}: JobCardProps): JSX.Element {
  const {job, error, replace} = useJob(id, initial, onFinal);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const onCancel = (): void => {
    cancelJob(id)
      .then(replace)
      .catch((failure: unknown) =>
        setCancelError(
          failure instanceof ApiError && failure.status === 409
            ? 'The job already started; a running job runs to its end.'
            : 'The cancel failed.',
        ),
      );
  };
  const params = Object.entries(job?.params ?? {});
  const log = job?.log ?? [];
  return (
    <section
      className="panel"
      aria-label={`Job ${id}`}
      data-testid="job-card"
      data-job-id={id}
      data-status={job?.status ?? 'loading'}
    >
      <div className="panel-head">
        <h3 className="panel-title">
          {job === null ? 'Job' : `Job: ${job.kind}`}
        </h3>
        {job !== null && <JobStatusTag status={job.status} />}
        <span className="num text-[11px] text-muted">{id}</span>
        <span className="ml-auto flex items-center gap-2">
          {job?.status === 'queued' && (
            <button
              type="button"
              className="btn"
              data-testid="job-cancel"
              onClick={onCancel}
            >
              Cancel
            </button>
          )}
          {linkToJob && (
            <a className="link text-[12px]" href={jobPath(id)}>
              Open job
            </a>
          )}
        </span>
      </div>
      <div className="panel-body space-y-3">
        {warnings.map(warning => (
          <p key={warning} className="notice notice-warn text-[12px]">
            {warning}
          </p>
        ))}
        {error !== null && (
          <p className="text-[12px] text-down" role="alert">
            {error}
          </p>
        )}
        {cancelError !== null && (
          <p className="text-[12px] text-down" role="alert">
            {cancelError}
          </p>
        )}
        {job === null && error === null && (
          <p className="text-[12px] text-muted">Loading the job.</p>
        )}
        {job !== null && (
          <>
            <JobProgress job={job} />
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 font-mono text-[11.5px] sm:grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)]">
              <dt className="text-muted">requested by</dt>
              <dd className="truncate text-ink">{job.requested_by}</dd>
              <dt className="text-muted">created</dt>
              <dd className="text-ink">{when(job.created_at)}</dd>
              <dt className="text-muted">started</dt>
              <dd className="text-ink">{when(job.started_at)}</dd>
              <dt className="text-muted">finished</dt>
              <dd className="text-ink">{when(job.finished_at)}</dd>
              <dt className="text-muted">params</dt>
              <dd className="break-words text-ink sm:col-span-3">
                {params.length === 0
                  ? 'none'
                  : params.map(([k, v]) => `${k}=${scalar(v)}`).join('  ')}
              </dd>
            </dl>
            {job.error !== null && (
              <p
                className="notice notice-down break-words font-mono text-[12px]"
                role="alert"
                data-testid="job-error"
              >
                {job.error}
              </p>
            )}
            {job.status === 'succeeded' && job.result !== null && (
              <JobResult result={job.result} />
            )}
            {log.length > 0 && (
              <div>
                <h4 className="section-title mb-1">
                  Log{' '}
                  <span className="num normal-case tracking-normal">
                    ({log.length} lines{isFinal(job) ? '' : ', live'})
                  </span>
                </h4>
                <pre
                  className="max-h-64 overflow-auto whitespace-pre-wrap border border-line bg-field p-2 font-mono text-[11px] leading-relaxed text-ink-2"
                  role="log"
                  aria-label="Job log"
                  data-testid="job-log"
                >
                  {log.join('\n')}
                </pre>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
