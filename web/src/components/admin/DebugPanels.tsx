import type {JSX} from 'react';
import {useState} from 'react';

import {debugRetrieve, debugUnderstand} from '../../api/admin';
import {ApiError} from '../../api/client';
import type {DebugRetrieve, DebugUnderstand} from '../../api/types';
import {EXAMPLES} from '../../lib/examples';
import {DebugAnalysis} from './DebugAnalysis';
import {DebugRetrievalPanel} from './DebugRetrievalPanel';
import {OpsPanelHead} from './OpsPanelHead';

/** The run state of the page. */
type Run =
  | {readonly kind: 'idle'}
  | {readonly kind: 'running'}
  | {readonly kind: 'error'; readonly message: string}
  | {
      readonly kind: 'ready';
      readonly analysis: DebugUnderstand;
      readonly retrieve: DebugRetrieve;
    };

/**
 * The page text of a failed debug run.
 *
 * @param error The error.
 * @return The text.
 */
function messageOf(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return `Rate limited: try again in ${error.retryAfter ?? 'a few'} seconds.`;
    }
    if (error.status === 503) {
      return 'The index is not loaded, so nothing can be retrieved.';
    }
    return error.message;
  }
  return 'The debug run failed.';
}

/**
 * The debug panels: a question box that runs understand and retrieve on
 * the loaded pipeline (no model request, D-02), then the analysis and the
 * retrieval with the scored context chunks.
 *
 * @return The panels.
 */
export function DebugPanels(): JSX.Element {
  const [question, setQuestion] = useState('');
  const [run, setRun] = useState<Run>({kind: 'idle'});
  const onRun = (): void => {
    const text = question.trim();
    if (text.length < 3) {
      setRun({kind: 'error', message: 'A question has at least 3 characters.'});
      return;
    }
    setRun({kind: 'running'});
    Promise.all([debugUnderstand(text), debugRetrieve(text)])
      .then(([analysis, retrieve]) =>
        setRun({kind: 'ready', analysis, retrieve}),
      )
      .catch((error: unknown) =>
        setRun({kind: 'error', message: messageOf(error)}),
      );
  };
  return (
    <>
      <section className="panel" aria-label="Debug question">
        <OpsPanelHead title="Debug a question">
          <span className="tag tag-up" data-testid="debug-requests">
            model requests: 0
          </span>
        </OpsPanelHead>
        <div className="panel-body space-y-3">
          <p className="text-[12.5px] text-ink-2">
            Shows how the pipeline reads a question and which chunks it would
            send, without asking the model: understanding and retrieval run on
            the loaded index, and no answer is written. Each run counts against
            your question rate limit.
          </p>
          <form
            className="flex flex-col gap-2 sm:flex-row sm:items-end"
            data-testid="debug-form"
            onSubmit={event => {
              event.preventDefault();
              onRun();
            }}
          >
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="section-title">Question</span>
              <input
                className="input min-w-0 text-[13px]"
                value={question}
                maxLength={1000}
                placeholder="What are the risk factors facing Apple?"
                data-testid="debug-question"
                onChange={event => setQuestion(event.target.value)}
              />
            </label>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={run.kind === 'running'}
              data-testid="debug-run"
            >
              Run
            </button>
          </form>
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map(example => (
              <button
                key={example.label}
                type="button"
                className="chip"
                onClick={() => setQuestion(example.question)}
              >
                {example.label}
              </button>
            ))}
          </div>
          {run.kind === 'running' && (
            <p className="text-[12px] text-muted" role="status">
              Understanding and retrieving.
            </p>
          )}
          {run.kind === 'error' && (
            <p
              className="notice notice-down text-[13px]"
              role="alert"
              data-testid="debug-error"
            >
              {run.message}
            </p>
          )}
        </div>
      </section>
      {run.kind === 'ready' && (
        <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <DebugAnalysis analysis={run.analysis} />
          {run.retrieve.retrieval === null ? (
            <p
              className="notice notice-warn text-[13px]"
              data-testid="debug-out-of-scope"
            >
              Out of scope: {run.retrieve.out_of_scope_reason ?? 'no reason'}.
              Nothing is retrieved for it.
            </p>
          ) : (
            <DebugRetrievalPanel retrieval={run.retrieve.retrieval} />
          )}
        </div>
      )}
    </>
  );
}
