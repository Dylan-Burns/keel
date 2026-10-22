import type {JSX} from 'react';

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
  high: 'border-emerald-300 bg-emerald-50 text-emerald-900',
  medium: 'border-amber-300 bg-amber-50 text-amber-900',
  low: 'border-red-300 bg-red-50 text-red-900',
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
  return (
    <section
      className="space-y-4"
      aria-label="Answer"
      data-testid="answer-area"
    >
      <ProgressSteps run={run} streaming={streaming} />
      {(answer !== null || run.deltas.length > 0) && (
        <AnswerMarkdown
          markdown={answerText(run)}
          streaming={answer === null}
        />
      )}
      {answer !== null && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span
            className={`rounded border px-2 py-0.5 ${CONFIDENCE[answer.confidence] ?? ''}`}
            data-testid="confidence-chip"
            title={answer.confidence_reason}
          >
            confidence {answer.confidence}
          </span>
          {coverage !== null && <CoverageIndicator coverage={coverage} />}
        </div>
      )}
      {run.findings.length > 0 && (
        <div className="space-y-2">
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
        <ComparisonTable table={answer.comparison_table} />
      )}
      {answer !== null && answer.gaps.length > 0 && (
        <div data-testid="gaps">
          <h2 className="text-sm font-medium">Gaps</h2>
          <ul className="list-disc pl-5 text-sm text-slate-700">
            {answer.gaps.map(gap => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      )}
      {answer !== null && answer.next_questions.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="Next questions">
          {answer.next_questions.map(next => (
            <li key={next}>
              <button
                type="button"
                className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:border-accent disabled:opacity-50"
                disabled={!askEnabled}
                onClick={() => onAsk(next)}
              >
                {next}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
