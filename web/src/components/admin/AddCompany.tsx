import type {JSX} from 'react';
import {useState} from 'react';

import {JobFeedback} from './JobFeedback';
import {OpsPanelHead} from './OpsPanelHead';
import {TICKER} from './tickers';
import {useJobLauncher} from './useJobLauncher';

/** Props of AddCompany. */
export interface AddCompanyProps {
  /** Called when the job ends, to reload what it changed. */
  readonly onDone: () => void;
}

/**
 * The add-a-company form: `keel add TICKER` as the `add` job.
 *
 * @param props Called when the job ends, to reload the watch list.
 * @return The panel.
 */
export function AddCompany({onDone}: AddCompanyProps): JSX.Element {
  const [ticker, setTicker] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const {state, launch} = useJobLauncher();
  const onSubmit = (): void => {
    const value = ticker.trim().toUpperCase();
    if (!TICKER.test(value)) {
      setProblem('A ticker has 1 to 10 letters, digits, dots, or dashes.');
      return;
    }
    setProblem(null);
    launch({kind: 'add', params: {ticker: value}});
  };
  return (
    <section className="panel" aria-label="Add a company">
      <OpsPanelHead title="Add a company" note="keel add TICKER" />
      <div className="panel-body space-y-3">
        <p className="text-[12.5px] text-ink-2">
          Fetches the latest 10-K and 10-Q of a company from SEC EDGAR, adds
          them to the corpus, and publishes an incremental index build. The
          server reloads the index when the job ends.
        </p>
        <form
          className="flex flex-wrap items-end gap-2"
          data-testid="add-form"
          onSubmit={event => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <label className="flex flex-col gap-1">
            <span className="section-title">Ticker</span>
            <input
              className="input w-36 font-mono uppercase"
              value={ticker}
              placeholder="ZTS"
              maxLength={10}
              autoComplete="off"
              data-testid="add-ticker"
              onChange={event => setTicker(event.target.value)}
            />
          </label>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={state.kind === 'sending'}
            data-testid="add-submit"
          >
            Add company
          </button>
        </form>
        {problem !== null && (
          <p className="text-[12px] text-down" role="alert">
            {problem}
          </p>
        )}
        <JobFeedback state={state} onFinal={onDone} />
      </div>
    </section>
  );
}
