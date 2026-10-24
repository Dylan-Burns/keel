import {useCallback, useState} from 'react';

import type {Job} from '../../api/types';
import type {LaunchState} from './useJobLauncher';
import {useJobLauncher} from './useJobLauncher';

/** The Add buttons of the company browser: 1 add job at a time. */
export interface CompanyAdder {
  /** The ticker of the last Add, whose row shows the job. */
  readonly target: string | null;
  readonly state: LaunchState;
  /** True while the job is sent or runs: every Add button is off. */
  readonly busy: boolean;
  readonly add: (ticker: string) => void;
  /** Called by the job card when the job reaches a final status. */
  readonly onFinal: (job: Job) => void;
}

/**
 * Starts the `add` job (`keel add TICKER`) from a company row and keeps
 * which row it came from. The job is heavy, so the server runs 1 at a
 * time; the page also turns off the other Add buttons until it ends, and
 * a 409 from another job shows in the row as the busy notice.
 *
 * @param onDone Called when the job ends, to reload what it changed.
 * @return The adder.
 */
export function useCompanyAdder(onDone: () => void): CompanyAdder {
  const {state, launch} = useJobLauncher();
  const [target, setTarget] = useState<string | null>(null);
  const [finished, setFinished] = useState<string | null>(null);
  const add = useCallback(
    (ticker: string): void => {
      setTarget(ticker);
      setFinished(null);
      launch({kind: 'add', params: {ticker}});
    },
    [launch],
  );
  const onFinal = useCallback(
    (job: Job): void => {
      setFinished(job.id);
      onDone();
    },
    [onDone],
  );
  const busy =
    state.kind === 'sending' ||
    (state.kind === 'started' && finished !== state.job.id);
  return {target, state, busy, add, onFinal};
}
