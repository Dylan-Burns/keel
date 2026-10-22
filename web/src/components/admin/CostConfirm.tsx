import type {JSX} from 'react';
import {useEffect, useId, useState} from 'react';

import {fetchCostPreview} from '../../api/admin';
import type {CostEstimate, CostQuery} from '../../api/types';
import {usd} from '../../lib/format';

/** Props of CostConfirm. */
export interface CostConfirmProps {
  /** The heading, such as `Run the eval`. */
  readonly title: string;
  /** The job parameters the preview prices. */
  readonly query: CostQuery;
  /** The label of the run button. */
  readonly actionLabel: string;
  /** Runs with `cost` when the job needs it, else with undefined. */
  readonly onConfirm: (confirm: string | undefined) => void;
  readonly onCancel: () => void;
  /** The `data-testid` of the panel. */
  readonly testId: string;
}

/** The load state of the preview. */
type Preview =
  | {readonly kind: 'loading'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly estimate: CostEstimate};

/**
 * The cost confirmation of a job that calls the model (eval with answers,
 * warm-cache): it loads `GET /api/admin/costs/preview`, shows the model
 * requests and the estimated dollars, and asks for an explicit tick before
 * it sends `confirm: "cost"`. A run that makes no model request goes
 * without the tick.
 *
 * @param props The props.
 * @return The panel.
 */
export function CostConfirm({
  title,
  query,
  actionLabel,
  onConfirm,
  onCancel,
  testId,
}: CostConfirmProps): JSX.Element {
  const [preview, setPreview] = useState<Preview>({kind: 'loading'});
  const [accepted, setAccepted] = useState(false);
  const checkId = useId();
  const key = JSON.stringify(query);
  useEffect(() => {
    let cancelled = false;
    fetchCostPreview(JSON.parse(key) as CostQuery)
      .then(estimate => {
        if (!cancelled) {
          setPreview({kind: 'ready', estimate});
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setPreview({
            kind: 'error',
            message:
              error instanceof Error
                ? `The cost preview failed: ${error.message}`
                : 'The cost preview failed.',
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [key]);
  const estimate = preview.kind === 'ready' ? preview.estimate : null;
  const needsCost = estimate?.confirm === 'cost';
  const ready = estimate !== null && (!needsCost || accepted);
  return (
    <section
      className="notice notice-warn space-y-2 text-[13px]"
      aria-label={title}
      data-testid={testId}
    >
      <p className="font-semibold">{title}</p>
      {preview.kind === 'loading' && (
        <p className="text-muted" role="status">
          Pricing the run.
        </p>
      )}
      {preview.kind === 'error' && (
        <p className="text-down" role="alert">
          {preview.message}
        </p>
      )}
      {estimate !== null && (
        <>
          <dl
            className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-0.5 font-mono text-[12px] sm:grid-cols-[auto_auto_auto_auto] sm:justify-start"
            data-testid={`${testId}-estimate`}
          >
            <dt className="text-muted">questions</dt>
            <dd className="text-ink">{estimate.questions}</dd>
            <dt className="text-muted">model requests</dt>
            <dd className="text-ink" data-testid={`${testId}-requests`}>
              {estimate.model_requests}
            </dd>
            <dt className="text-muted">judge requests</dt>
            <dd className="text-ink">{estimate.judge_requests}</dd>
            <dt className="text-muted">per answer</dt>
            <dd className="text-ink">{usd(estimate.answer_usd, 4)}</dd>
            <dt className="text-muted">estimated total</dt>
            <dd
              className="font-semibold text-warn"
              data-testid={`${testId}-usd`}
            >
              {usd(estimate.usd)}
            </dd>
            <dt className="text-muted">basis</dt>
            <dd className="text-ink">
              {estimate.basis === 'audit'
                ? 'measured from the audit log'
                : 'priced from config/prices.yaml'}
            </dd>
          </dl>
          {needsCost ? (
            <label
              className="flex items-start gap-2 text-ink"
              htmlFor={checkId}
            >
              <input
                id={checkId}
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-[var(--k-accent)]"
                checked={accepted}
                data-testid={`${testId}-accept`}
                onChange={event => setAccepted(event.target.checked)}
              />
              <span>
                I accept about {usd(estimate.usd)} for{' '}
                {estimate.model_requests + estimate.judge_requests} model
                requests, charged to the daily budget.
              </span>
            </label>
          ) : (
            <p className="text-ink-2">This run makes no model request.</p>
          )}
        </>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn btn-primary"
          disabled={!ready}
          data-testid={`${testId}-submit`}
          onClick={() => onConfirm(needsCost ? 'cost' : undefined)}
        >
          {actionLabel}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}
