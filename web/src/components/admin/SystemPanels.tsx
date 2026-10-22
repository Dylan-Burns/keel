import type {JSX} from 'react';
import {useCallback, useEffect, useState} from 'react';

import {fetchSystem} from '../../api/admin';
import type {SystemResponse} from '../../api/types';
import {jobPath} from '../../lib/links';
import {AuditPanel} from './AuditPanel';
import {BackupsPanel} from './BackupsPanel';
import {DoctorPanel} from './DoctorPanel';
import {MaintenancePanel} from './MaintenancePanel';
import {SystemOverview} from './SystemOverview';

/** The load state of the system data. */
type Load =
  | {readonly kind: 'loading'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly data: SystemResponse};

/**
 * The panels of the system page: the overview, the doctor checks, the
 * maintenance jobs, the backups, and the admin audit. A job that ends
 * reloads the data.
 *
 * @return The panels.
 */
export function SystemPanels(): JSX.Element {
  const [load, setLoad] = useState<Load>({kind: 'loading'});
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion(n => n + 1), []);
  useEffect(() => {
    let cancelled = false;
    fetchSystem()
      .then(data => {
        if (!cancelled) {
          setLoad({kind: 'ready', data});
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoad({kind: 'error', message: 'The system data could not load.'});
        }
      });
    return () => {
      cancelled = true;
    };
  }, [version]);
  if (load.kind === 'loading') {
    return <p className="text-[13px] text-muted">Loading the system data.</p>;
  }
  if (load.kind === 'error') {
    return (
      <p className="notice notice-down text-[13px]" role="alert">
        {load.message}
      </p>
    );
  }
  const {data} = load;
  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        {data.active_job !== null && (
          <p
            className="notice notice-warn text-[12.5px]"
            data-testid="sys-active"
          >
            The {data.active_job.kind} job{' '}
            <a className="link font-mono" href={jobPath(data.active_job.id)}>
              {data.active_job.id.slice(0, 8)}
            </a>{' '}
            is {data.active_job.status}: another heavy job is refused until it
            ends.
          </p>
        )}
        <button type="button" className="btn ml-auto" onClick={reload}>
          Reload
        </button>
      </div>
      <SystemOverview system={data} />
      <div className="grid items-start gap-3 xl:grid-cols-2">
        <MaintenancePanel onDone={reload} />
        <BackupsPanel backups={data.backups} onDone={reload} />
      </div>
      <DoctorPanel checks={data.doctor} failed={data.doctor_failed} />
      <AuditPanel version={version} />
    </>
  );
}
