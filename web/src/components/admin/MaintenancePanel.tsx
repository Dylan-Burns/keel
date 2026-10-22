import type {JSX} from 'react';
import {useState} from 'react';

import type {Job} from '../../api/types';
import {CostConfirm} from './CostConfirm';
import {JobFeedback} from './JobFeedback';
import {OpsPanelHead} from './OpsPanelHead';
import {TypedConfirm} from './TypedConfirm';
import {useJobLauncher} from './useJobLauncher';

/** Props of MaintenancePanel. */
export interface MaintenancePanelProps {
  /** Called when a job ends, to reload the page. */
  readonly onDone: (job: Job) => void;
}

/** The confirmation open now, if any. */
type Asking = 'none' | 'index' | 'warm' | 'eval';

/**
 * The heavy jobs of the system page: Rebuild index (`keel index`, behind a
 * typed `rebuild` with the memory and time warning), Warm cache
 * (`keel warm-cache`) and Run eval (`keel eval`), each behind the cost
 * preview and an explicit tick before it sends `confirm: "cost"` when it
 * calls the model.
 *
 * @param props The props.
 * @return The panel.
 */
export function MaintenancePanel({onDone}: MaintenancePanelProps): JSX.Element {
  const {state, launch} = useJobLauncher();
  const [asking, setAsking] = useState<Asking>('none');
  const [incremental, setIncremental] = useState(false);
  const [warmRefresh, setWarmRefresh] = useState(false);
  const [factsOnly, setFactsOnly] = useState(false);
  const [answers, setAnswers] = useState(false);
  const [judge, setJudge] = useState(true);
  const [ablation, setAblation] = useState(true);
  const [subset, setSubset] = useState('');
  const subsetValue = subset.trim() === '' ? null : subset.trim();
  const close = (): void => setAsking('none');
  const busy = state.kind === 'sending';
  return (
    <section
      className="panel"
      aria-label="Maintenance jobs"
      data-testid="sys-maintenance"
    >
      <OpsPanelHead title="Maintenance jobs" />
      <div className="divide-y divide-line">
        <div className="panel-body space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="section-title">Index</h3>
            <code className="font-mono text-[10.5px] text-muted">
              keel index [--incremental]
            </code>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="btn"
              disabled={busy}
              data-testid="index-rebuild"
              onClick={() => setAsking('index')}
            >
              Rebuild index
            </button>
            <label className="flex items-center gap-2 text-[12.5px] text-ink-2">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--k-accent)]"
                checked={incremental}
                onChange={event => setIncremental(event.target.checked)}
              />
              Incremental (skip unchanged files)
            </label>
          </div>
          {asking === 'index' && (
            <TypedConfirm
              title={
                incremental
                  ? 'Rebuild the index (incremental)'
                  : 'Rebuild the index'
              }
              expected="rebuild"
              actionLabel="Rebuild"
              testId="index-confirm"
              onCancel={close}
              onConfirm={typed => {
                close();
                launch({kind: 'index', params: {incremental}, confirm: typed});
              }}
            >
              A full build needs about 6.6 GB of memory and runs for more than
              an hour on the pilot host. Questions keep the current build until
              the new one is published, then the server reloads it.
            </TypedConfirm>
          )}
        </div>
        <div className="panel-body space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="section-title">Answer cache</h3>
            <code className="font-mono text-[10.5px] text-muted">
              keel warm-cache [--refresh] [--facts-only]
            </code>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="btn"
              disabled={busy}
              data-testid="warm-cache"
              onClick={() =>
                factsOnly
                  ? launch({
                      kind: 'warm_cache',
                      params: {refresh: false, facts_only: true},
                    })
                  : setAsking('warm')
              }
            >
              Warm cache
            </button>
            <label className="flex items-center gap-2 text-[12.5px] text-ink-2">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--k-accent)]"
                checked={warmRefresh}
                disabled={factsOnly}
                onChange={event => setWarmRefresh(event.target.checked)}
              />
              Answer every demo question again
            </label>
            <label className="flex items-center gap-2 text-[12.5px] text-ink-2">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--k-accent)]"
                checked={factsOnly}
                onChange={event => setFactsOnly(event.target.checked)}
              />
              Facts only (no model request)
            </label>
          </div>
          {asking === 'warm' && (
            <CostConfirm
              title="Warm the answer cache"
              query={{
                kind: 'warm_cache',
                refresh: warmRefresh,
                facts_only: false,
              }}
              actionLabel="Warm cache"
              testId="warm-confirm"
              onCancel={close}
              onConfirm={confirm => {
                close();
                launch({
                  kind: 'warm_cache',
                  params: {refresh: warmRefresh, facts_only: false},
                  ...(confirm === undefined ? {} : {confirm}),
                });
              }}
            />
          )}
        </div>
        <div className="panel-body space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="section-title">Evaluation</h3>
            <code className="font-mono text-[10.5px] text-muted">
              keel eval [--answers] [--no-judge] [--subset S]
            </code>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-[12.5px] text-ink-2">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--k-accent)]"
                checked={answers}
                data-testid="eval-answers"
                onChange={event => setAnswers(event.target.checked)}
              />
              Answer the golden questions (calls the model)
            </label>
            <label className="flex items-center gap-2 text-[12.5px] text-ink-2">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--k-accent)]"
                checked={judge}
                disabled={!answers}
                onChange={event => setJudge(event.target.checked)}
              />
              Judge
            </label>
            <label className="flex items-center gap-2 text-[12.5px] text-ink-2">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--k-accent)]"
                checked={ablation}
                onChange={event => setAblation(event.target.checked)}
              />
              Ablation
            </label>
            <label className="flex items-center gap-2 text-[12.5px] text-ink-2">
              Subset
              <input
                className="input w-40 font-mono"
                value={subset}
                placeholder="G-01,G-02 or a tag"
                maxLength={200}
                onChange={event => setSubset(event.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn"
              disabled={busy}
              data-testid="eval-run"
              onClick={() =>
                answers
                  ? setAsking('eval')
                  : launch({
                      kind: 'eval',
                      params: {
                        answers: false,
                        judge,
                        subset: subsetValue,
                        ablation,
                      },
                    })
              }
            >
              Run eval
            </button>
          </div>
          {asking === 'eval' && (
            <CostConfirm
              title="Run the eval with answers"
              query={{kind: 'eval', answers: true, judge, subset: subsetValue}}
              actionLabel="Run eval"
              testId="eval-confirm"
              onCancel={close}
              onConfirm={confirm => {
                close();
                launch({
                  kind: 'eval',
                  params: {answers: true, judge, subset: subsetValue, ablation},
                  ...(confirm === undefined ? {} : {confirm}),
                });
              }}
            />
          )}
        </div>
        <div className="panel-body empty:hidden">
          <JobFeedback state={state} onFinal={onDone} />
        </div>
      </div>
    </section>
  );
}
