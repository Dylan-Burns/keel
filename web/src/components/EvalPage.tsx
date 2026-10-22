import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';
import {useEffect, useState} from 'react';

import {ApiError, fetchEval, getToken, setToken} from '../api/client';
import type {EvalResponse} from '../api/types';
import {evalPage, pick} from '../motion/presets';
import {GateBar} from './GateBar';
import {MarkdownDocument} from './MarkdownDocument';
import {TokenField} from './TokenField';

/** The load state of the page. */
type Load =
  | {readonly kind: 'loading'}
  | {readonly kind: 'no_token'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly data: EvalResponse};

/**
 * The eval page at `/eval` (W-02, chapter 25.2): the regression gates as
 * metric bars, then `eval/report.md` and `docs/PROMPT_LOG.md`, read-only,
 * through the answer renderer and DOMPurify. The page has no logic beyond
 * the render; `keel eval` writes the report.
 *
 * @return The page.
 */
export function EvalPage(): JSX.Element {
  const reduced = useReducedMotion();
  const [tokenCount, setTokenCount] = useState(0);
  const [load, setLoad] = useState<Load>(() =>
    getToken() === null ? {kind: 'no_token'} : {kind: 'loading'},
  );
  useEffect(() => {
    if (getToken() === null) {
      return;
    }
    let cancelled = false;
    fetchEval()
      .then(data => {
        if (!cancelled) {
          setLoad({kind: 'ready', data});
        }
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          setLoad({kind: 'no_token'});
        } else {
          setLoad({kind: 'error', message: 'The eval page could not load.'});
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tokenCount]);
  const onSave = (token: string): void => {
    setToken(token);
    setLoad({kind: 'loading'});
    setTokenCount(n => n + 1);
  };
  return (
    <div
      className="min-h-screen bg-paper font-sans text-ink"
      data-testid="eval-page"
      data-load={load.kind}
    >
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
        <h1 className="text-lg font-semibold">Keel evaluation</h1>
        <button
          type="button"
          className="text-sm text-accent underline"
          onClick={() => window.location.assign('/')}
        >
          Back to questions
        </button>
        <div className="ml-auto">
          <TokenField
            hasToken={load.kind !== 'no_token'}
            rejected={load.kind === 'no_token' && getToken() !== null}
            onSave={onSave}
          />
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl space-y-8 px-4 py-6">
        {load.kind === 'no_token' && (
          <p className="text-sm text-slate-600">
            Enter the access token to read the eval report.
          </p>
        )}
        {load.kind === 'loading' && (
          <p className="text-sm text-slate-600">Loading the eval report.</p>
        )}
        {load.kind === 'error' && (
          <p className="text-sm text-red-700" role="alert">
            {load.message}
          </p>
        )}
        {load.kind === 'ready' && (
          <>
            <section className="space-y-3" aria-label="Regression gates">
              <h2 className="text-lg font-semibold">Regression gates</h2>
              {load.data.gates.length === 0 ? (
                <p
                  className="text-sm text-slate-600"
                  data-testid="eval-no-gates"
                >
                  No gates yet: the report is missing or has no gates table.
                </p>
              ) : (
                <motion.ul
                  className="space-y-3"
                  variants={pick(evalPage.bars, reduced)}
                  initial="hidden"
                  animate="visible"
                >
                  {load.data.gates.map(gate => (
                    <GateBar key={gate.name} gate={gate} reduced={reduced} />
                  ))}
                </motion.ul>
              )}
            </section>
            <MarkdownDocument
              title="Eval report"
              document={load.data.report}
              empty="No eval report yet. Run keel eval to write eval/report.md, then reload this page."
              testId="eval-report"
            />
            <MarkdownDocument
              title="Prompt log"
              document={load.data.prompt_log}
              empty="No prompt log in this deployment."
              testId="eval-prompt-log"
            />
          </>
        )}
      </main>
    </div>
  );
}
