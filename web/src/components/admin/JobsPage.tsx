import type {JSX} from 'react';
import {useCallback, useState} from 'react';

import {jobIdOf} from '../../lib/links';
import {AdminShell} from './AdminShell';
import {JobCard} from './JobCard';
import {JobsPanel} from './JobsPanel';

/**
 * The jobs page at `/jobs` and `/jobs/{id}` (admins): the list of the admin
 * jobs, and the job of the path with its live progress, log, result, and
 * cancel. The CLI twin is `keel jobs [ID]`.
 *
 * @return The page.
 */
export function JobsPage(): JSX.Element {
  const selected = jobIdOf(window.location.pathname);
  const [version, setVersion] = useState(0);
  const onFinal = useCallback(() => setVersion(n => n + 1), []);
  return (
    <AdminShell title="Jobs" current="jobs" adminOnly testId="jobs-page">
      {() => (
        <>
          {selected !== null && (
            <JobCard
              key={selected}
              id={selected}
              linkToJob={false}
              onFinal={onFinal}
            />
          )}
          <JobsPanel selected={selected} version={version} />
        </>
      )}
    </AdminShell>
  );
}
