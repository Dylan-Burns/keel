import type {JSX} from 'react';
import {useCallback} from 'react';

import {inlineChipFor} from '../lib/citations';

import type {Run} from '../state';
import {answerText} from '../state';
import {AnswerMarkdown} from './AnswerMarkdown';
import {ComparisonTable} from './ComparisonTable';
import {CoverageIndicator} from './CoverageIndicator';
import {FindingsGroup} from './FindingsGroup';
import {ProgressSteps} from './ProgressSteps';

/** Props of AnswerArea. */
export interface AnswerAreaProps {
  readonly run: Run;
  /** True between the first `answer_delta` and the `final` event. */
  readonly streaming: boolean;
  readonly askEnabled: boolean;
  readonly onSelectCitation: (chunkId: string) => void;
  readonly onAsk: (question: string) => void;
}

const CONFIDENCE: Readonly<Record<string, string>> = {
  high: 'tag-up',
  medium: 'tag-warn',
  low: 'tag-down',
};

/**
 * The answer area (chapter 14.5): the progress line, the direct answer as it
 * streams, then the findings per company, the comparison table, the gaps,
 * the coverage indicator, the confidence chip, and the next questions.
 *
 * @param props The props.
 * @return The answer area.
 */
export function AnswerArea({
  run,
  streaming,
  askEnabled,
  onSelectCitation,
  onAsk,
}: AnswerAreaProps): JSX.Element {
  const answer = run.final?.answer ?? null;
  const coverage =
    answer !== null && 'companies_used' in answer.coverage
      ? answer.coverage
      : null;
  const resolveCitation = useCallback(
    (chunkId: string) => inlineChipFor(run, chunkId),
    [run],
  );
  return (
    <section className="panel" aria-label="Answer" data-testid="answer-area">
      <div className="panel-head">
        <h2 className="panel-title">Answer</h2>
        {answer !== null && (
          <span
            className={`tag ${CONFIDENCE[answer.confidence] ?? ''}`}
            data-testid="confidence-chip"
            title={answer.confidence_reason}
          >
            confidence {answer.confidence}
          </span>
        )}
        <div className="ml-auto">
          <ProgressSteps run={run} streaming={streaming} />
        </div>
      </div>
      <div className="panel-body space-y-4">
        {(answer !== null || run.deltas.length > 0) && (
          <AnswerMarkdown
            markdown={answerText(run)}
            streaming={streaming}
            resolveCitation={resolveCitation}
            citationsClickable={run.final !== null}
            onSelectCitation={onSelectCitation}
          />
        )}
        {answer === null && run.deltas.length === 0 && (
          <p className="font-mono text-xs text-muted" role="status">
            Reading the filings.
          </p>
        )}
        {coverage !== null && <CoverageIndicator coverage={coverage} />}
        {run.findings.length > 0 && (
          <div className="space-y-1.5">
            <h3 className="section-title">Findings by company</h3>
            {run.findings.map(company => (
              <FindingsGroup
                key={company.ticker}
                run={run}
                company={company}
                onSelectCitation={onSelectCitation}
              />
            ))}
          </div>
        )}
        {answer?.comparison_table && (
          <div className="space-y-1.5">
            <h3 className="section-title">Comparison</h3>
            <ComparisonTable table={answer.comparison_table} />
          </div>
        )}
        {answer !== null && answer.gaps.length > 0 && (
          <div className="space-y-1.5" data-testid="gaps">
            <h3 className="section-title">Gaps</h3>
            <ul className="space-y-1 border-l-2 border-warn pl-3 text-[13px] text-ink-2">
              {answer.gaps.map(gap => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          </div>
        )}
        {answer !== null && answer.next_questions.length > 0 && (
          <div className="space-y-1.5">
            <h3 className="section-title">Next questions</h3>
            <ul className="flex flex-wrap gap-1.5" aria-label="Next questions">
              {answer.next_questions.map(next => (
                <li key={next}>
                  <button
                    type="button"
                    className="chip"
                    disabled={!askEnabled}
                    onClick={() => onAsk(next)}
                  >
                    {next}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
