import {useCallback, useEffect, useRef, useState} from 'react';

import {fetchJob} from '../../api/admin';
import type {Job} from '../../api/types';
import {POLL_MS, isFinal} from './useJob';
import {useJobLauncher} from './useJobLauncher';

/** What the row of the last Add shows in its action cell. */
export type AddOutcome =
  | {readonly kind: 'running'}
  | {
      /** The job failed, was refused, or another job holds the slot. */
      readonly kind: 'failed';
      readonly message: string;
      /** The job to open for the detail, or null when none was queued. */
      readonly jobId: string | null;
    };

/** The Add buttons of the company browser: 1 add job at a time. */
export interface CompanyAdder {
  /** The ticker of the last Add. */
  readonly target: string | null;
  /** The state of the last Add, or null once it succeeded or before one. */
  readonly outcome: AddOutcome | null;
  /** True while the job is sent or runs: every Add button is off. */
  readonly busy: boolean;
  readonly add: (ticker: string) => void;
}

/**
 * The failure text of a job that ended without success.
 *
 * @param job The final job.
 * @return The error of the job, or its status.
 */
function failureOf(job: Job): string {
  return job.error ?? `The add job ${job.status}.`;
}

/**
 * Starts the `add` job (`keel add TICKER`) from a company row, polls it
 * to its end, and keeps which row it came from. The row shows the state
 * in its own button, so the table never grows a row. The job is heavy, so
 * the server runs 1 at a time; the page also turns off the other Add
 * buttons until it ends. When the job succeeds the browser reloads, and
 * the row turns into an indexed company with Financials and Update.
 *
 * @param onDone Called when the job ends, to reload what it changed.
 * @return The adder.
 */
export function useCompanyAdder(onDone: () => void): CompanyAdder {
  const {state, launch} = useJobLauncher();
  const [target, setTarget] = useState<string | null>(null);
  const [final, setFinal] = useState<Job | null>(null);
  const doneRef = useRef(onDone);
  useEffect(() => {
    doneRef.current = onDone;
  });
  const add = useCallback(
    (ticker: string): void => {
      setTarget(ticker);
      setFinal(null);
      launch({kind: 'add', params: {ticker}});
    },
    [launch],
  );
  const started = state.kind === 'started' ? state.job : null;
  useEffect(() => {
    if (started === null) {
      return undefined;
    }
    let cancelled = false;
    let timer: number | undefined;
    const settle = (job: Job): void => {
      setFinal(job);
      doneRef.current();
    };
    const poll = (): void => {
      fetchJob(started.id)
        .then(job => {
          if (cancelled) {
            return;
          }
          if (isFinal(job)) {
            settle(job);
            return;
          }
          timer = window.setTimeout(poll, POLL_MS);
        })
        .catch(() => {
          if (!cancelled) {
            timer = window.setTimeout(poll, POLL_MS * 2);
          }
        });
    };
    if (isFinal(started)) {
      settle(started);
    } else {
      poll();
    }
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [started]);
  const running =
    state.kind === 'sending' ||
    (started !== null && (final === null || final.id !== started.id));
  let outcome: AddOutcome | null = null;
  if (running) {
    outcome = {kind: 'running'};
  } else if (state.kind === 'busy') {
    outcome = {kind: 'failed', message: state.message, jobId: state.jobId};
  } else if (state.kind === 'failed') {
    outcome = {kind: 'failed', message: state.message, jobId: null};
  } else if (final !== null && final.status !== 'succeeded') {
    outcome = {kind: 'failed', message: failureOf(final), jobId: final.id};
  }
  return {target, outcome, busy: running, add};
}
