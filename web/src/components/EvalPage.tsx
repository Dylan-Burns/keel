import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';
import {useEffect, useMemo, useState} from 'react';

import {ApiError, fetchEval, getToken, setToken} from '../api/client';
import type {EvalResponse} from '../api/types';
import {guideFor} from '../lib/evalGuide';
import {parseReport, reportJson} from '../lib/evalReport';
import {saveBlob} from '../lib/download';
import {evalPage, pick} from '../motion/presets';
import {EvalGuide} from './eval/EvalGuide';
import {EvalOverview} from './eval/EvalOverview';
import {GateBar} from './GateBar';
import {MarkdownDocument} from './MarkdownDocument';
import {PageBar} from './PageBar';
import {TokenField} from './TokenField';

/** The load state of the page. */
type Load =
  | {readonly kind: 'loading'}
  | {readonly kind: 'no_token'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly data: EvalResponse};

/**
 * The eval page at `/eval` (W-02, chapter 25.2): the regression gates as
 * metric bars, the headline numbers and charts of the run, then
 * `eval/report.md` with a plain-language note under each section and its
 * Markdown and JSON downloads, then `docs/PROMPT_LOG.md`, read-only,
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
  const markdown = load.kind === 'ready' ? load.data.report.markdown : null;
  const parsed = useMemo(
    () => (markdown === null ? null : parseReport(markdown)),
    [markdown],
  );
  const stem = `keel-${parsed?.run['Run ID'] ?? 'eval-report'}`;
  const onSave = (token: string): void => {
    setToken(token);
    setLoad({kind: 'loading'});
    setTokenCount(n => n + 1);
  };
  return (
    <div
      className="min-h-screen bg-canvas font-sans text-ink"
      data-testid="eval-page"
      data-load={load.kind}
    >
      <PageBar title="Evaluation">
        <TokenField
          hasToken={load.kind !== 'no_token'}
          rejected={load.kind === 'no_token' && getToken() !== null}
          onSave={onSave}
        />
      </PageBar>
      <main className="mx-auto w-full max-w-[1400px] space-y-3 px-3 py-3">
        {load.kind === 'no_token' && (
          <p className="text-[13px] text-muted">
            Enter the access token to read the eval report.
          </p>
        )}
        {load.kind === 'loading' && (
          <p className="text-[13px] text-muted">Loading the eval report.</p>
        )}
        {load.kind === 'error' && (
          <p className="notice notice-down text-[13px]" role="alert">
            {load.message}
          </p>
        )}
        {load.kind === 'ready' && (
          <>
            <section className="panel" aria-label="Regression gates">
              <div className="panel-head">
                <h2 className="panel-title">Regression gates</h2>
              </div>
              {load.data.gates.length === 0 ? (
                <p
                  className="panel-body text-[13px] text-muted"
                  data-testid="eval-no-gates"
                >
                  No gates yet: the report is missing or has no gates table.
                </p>
              ) : (
                <motion.ul
                  className="divide-y divide-line"
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
            {parsed !== null && (
              <EvalOverview report={parsed} gates={load.data.gates} />
            )}
            <MarkdownDocument
              title="Eval report"
              document={load.data.report}
              empty="No eval report yet. Run keel eval to write eval/report.md, then reload this page."
              testId="eval-report"
              noteFor={heading => {
                const guide = guideFor(heading);
                return guide === null ? null : <EvalGuide guide={guide} />;
              }}
              {...(markdown === null || parsed === null
                ? {}
                : {
                    actions: (
                      <>
                        <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted">
                          Download
                        </span>
                        <button
                          type="button"
                          className="btn"
                          title="The report file as keel eval writes it"
                          data-testid="eval-download-md"
                          onClick={() =>
                            saveBlob(
                              `${stem}.md`,
                              new Blob([markdown], {type: 'text/markdown'}),
                            )
                          }
                        >
                          Markdown
                        </button>
                        <button
                          type="button"
                          className="btn"
                          title="The run details and every table as rows of named fields"
                          data-testid="eval-download-json"
                          onClick={() =>
                            saveBlob(
                              `${stem}.json`,
                              new Blob(
                                [
                                  `${JSON.stringify(reportJson(parsed), null, 2)}\n`,
                                ],
                                {type: 'application/json'},
                              ),
                            )
                          }
                        >
                          JSON
                        </button>
                      </>
                    ),
                  })}
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
