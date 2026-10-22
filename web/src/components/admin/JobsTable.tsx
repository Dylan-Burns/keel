import type {JSX} from 'react';

import type {Job} from '../../api/types';
import {when} from '../../lib/format';
import {jobPath} from '../../lib/links';
import {JobStatusTag} from './JobStatusTag';

/** Props of JobsTable. */
export interface JobsTableProps {
  readonly jobs: readonly Job[];
  /** The job open in the detail, highlighted. */
  readonly selected: string | null;
}

/**
 * The admin jobs, newest first: the ID (a link to the job), the kind, the
 * status, the phase, the progress, who asked, and when. The table scrolls
 * inside its box on a phone.
 *
 * @param props The props.
 * @return The table.
 */
export function JobsTable({jobs, selected}: JobsTableProps): JSX.Element {
  return (
    <div className="overflow-x-auto">
      <table className="grid-table" data-testid="jobs-table">
        <thead>
          <tr>
            <th scope="col">Job</th>
            <th scope="col">Kind</th>
            <th scope="col">Status</th>
            <th scope="col">Phase</th>
            <th scope="col" className="text-right">
              Progress
            </th>
            <th scope="col">By</th>
            <th scope="col">Created</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map(job => (
            <tr
              key={job.id}
              data-testid="jobs-row"
              data-job-id={job.id}
              aria-current={job.id === selected ? 'true' : undefined}
              className={
                job.id === selected ? 'outline outline-1 outline-accent' : ''
              }
            >
              <td>
                <a
                  className="link font-mono text-[11.5px]"
                  href={jobPath(job.id)}
                >
                  {job.id.slice(0, 8)}
                </a>
              </td>
              <td className="font-mono text-[11.5px]">{job.kind}</td>
              <td>
                <JobStatusTag status={job.status} />
              </td>
              <td className="text-[12px] text-ink-2">{job.phase}</td>
              <td className="cell-num text-[11.5px]">
                {job.progress.total === null
                  ? job.progress.done || ''
                  : `${job.progress.done}/${job.progress.total}`}
              </td>
              <td className="font-mono text-[11.5px] text-ink-2">
                {job.requested_by}
              </td>
              <td className="num whitespace-nowrap text-[11.5px] text-ink-2">
                {when(job.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
