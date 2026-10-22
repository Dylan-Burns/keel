import type {JSX} from 'react';
import {useState} from 'react';

import {JobFeedback} from './JobFeedback';
import {OpsPanelHead} from './OpsPanelHead';
import {TICKER} from './tickers';
import {useJobLauncher} from './useJobLauncher';

/**
 * The company facts panel: `keel facts TICKER` as the light `facts` job.
 *
 * @return The panel.
 */
export function FactsPanel(): JSX.Element {
  const [ticker, setTicker] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const {state, launch} = useJobLauncher();
  return (
    <section className="panel" aria-label="Company facts">
      <OpsPanelHead title="Company facts" note="keel facts TICKER" />
      <div className="panel-body space-y-3">
        <p className="text-[12.5px] text-ink-2">
          Fetches the XBRL company facts from EDGAR and shows the facts lines an
          answer would carry. A light job: it queues behind a running job.
        </p>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={event => {
            event.preventDefault();
            const value = ticker.trim().toUpperCase();
            if (!TICKER.test(value)) {
              setProblem(
                'A ticker has 1 to 10 letters, digits, dots, or dashes.',
              );
              return;
            }
            setProblem(null);
            launch({kind: 'facts', params: {ticker: value}});
          }}
        >
          <label className="flex flex-col gap-1">
            <span className="section-title">Ticker</span>
            <input
              className="input w-36 font-mono uppercase"
              value={ticker}
              placeholder="NVDA"
              maxLength={10}
              autoComplete="off"
              data-testid="facts-ticker"
              onChange={event => setTicker(event.target.value)}
            />
          </label>
          <button
            type="submit"
            className="btn"
            disabled={state.kind === 'sending'}
            data-testid="facts-submit"
          >
            Fetch facts
          </button>
        </form>
        {problem !== null && (
          <p className="text-[12px] text-down" role="alert">
            {problem}
          </p>
        )}
        <JobFeedback state={state} />
      </div>
    </section>
  );
}
