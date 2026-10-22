import type {JSX} from 'react';
import {useEffect, useState} from 'react';

import {fetchJobs} from '../../api/admin';
import type {JobList} from '../../api/types';
import {jobPath} from '../../lib/links';
import {JobsTable} from './JobsTable';
import {OpsPanelHead} from './OpsPanelHead';
import {FINAL_STATUSES} from './useJob';

/** The list refresh interval while a job is queued or running. */
export const LIST_POLL_MS = 3000;

/** Props of JobsPanel. */
export interface JobsPanelProps {
  /** The job open in the detail, or null. */
  readonly selected: string | null;
  /** A counter the page bumps to reload the list. */
  readonly version: number;
}

/** The load state of the list. */
type Load =
  | {readonly kind: 'loading'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly data: JobList};

/**
 * The jobs list (`keel jobs`): it reloads every 3 s while a job is queued
 * or running, and stops when none is.
 *
 * @param props The props.
 * @return The panel.
 */
export function JobsPanel({selected, version}: JobsPanelProps): JSX.Element {
  const [load, setLoad] = useState<Load>({kind: 'loading'});
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    fetchJobs(50)
      .then(data => {
        if (cancelled) {
          return;
        }
        setLoad({kind: 'ready', data});
        if (data.items.some(job => !FINAL_STATUSES.has(job.status))) {
          timer = window.setTimeout(() => setTick(n => n + 1), LIST_POLL_MS);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoad({kind: 'error', message: 'The jobs could not load.'});
        }
      });
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [version, tick]);
  const active = load.kind === 'ready' ? load.data.active : null;
  return (
    <section className="panel" aria-label="Jobs" data-testid="jobs-panel">
      <OpsPanelHead title="Jobs" note="keel jobs [ID]">
        <button
          type="button"
          className="btn"
          onClick={() => setTick(n => n + 1)}
        >
          Reload
        </button>
      </OpsPanelHead>
      {active !== null && (
        <p
          className="border-b border-line px-3 py-2 text-[12.5px] text-ink-2"
          data-testid="jobs-active"
        >
          The {active.kind} job{' '}
          <a className="link font-mono" href={jobPath(active.id)}>
            {active.id.slice(0, 8)}
          </a>{' '}
          holds the maintenance slot ({active.status}); another heavy job waits
          for it to end.
        </p>
      )}
      {load.kind === 'loading' && (
        <p className="panel-body text-[12px] text-muted">Loading the jobs.</p>
      )}
      {load.kind === 'error' && (
        <p className="panel-body text-[12px] text-down" role="alert">
          {load.message}
        </p>
      )}
      {load.kind === 'ready' && load.data.items.length === 0 && (
        <p
          className="panel-body text-[12px] text-muted"
          data-testid="jobs-empty"
        >
          No jobs yet. Start one from the companies or system page.
        </p>
      )}
      {load.kind === 'ready' && load.data.items.length > 0 && (
        <JobsTable jobs={load.data.items} selected={selected} />
      )}
    </section>
  );
}
