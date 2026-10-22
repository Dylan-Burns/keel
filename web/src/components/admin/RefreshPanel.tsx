import type {JSX} from 'react';

import {JobFeedback} from './JobFeedback';
import {OpsPanelHead} from './OpsPanelHead';
import {useJobLauncher} from './useJobLauncher';

/** Props of RefreshPanel. */
export interface RefreshPanelProps {
  /** Called when the job ends, to reload what it changed. */
  readonly onDone: () => void;
}

/**
 * The refresh panel: `keel refresh --dry-run` lists the new filings of the
 * watched tickers; `keel refresh` adds them.
 *
 * @param props Called when the job ends.
 * @return The panel.
 */
export function RefreshPanel({onDone}: RefreshPanelProps): JSX.Element {
  const {state, launch} = useJobLauncher();
  return (
    <section className="panel" aria-label="Refresh">
      <OpsPanelHead title="Refresh" note="keel refresh [--dry-run]" />
      <div className="panel-body space-y-3">
        <p className="text-[12.5px] text-ink-2">
          Checks EDGAR for new filings of every watched ticker. A dry run only
          lists them; a refresh adds them and reloads the index.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn"
            disabled={state.kind === 'sending'}
            data-testid="refresh-dry-run"
            onClick={() => launch({kind: 'refresh', params: {dry_run: true}})}
          >
            Dry run
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={state.kind === 'sending'}
            data-testid="refresh-run"
            onClick={() => launch({kind: 'refresh', params: {dry_run: false}})}
          >
            Run refresh
          </button>
        </div>
        <JobFeedback state={state} onFinal={onDone} />
      </div>
    </section>
  );
}
