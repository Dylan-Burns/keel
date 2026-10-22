import type {FormEvent, JSX, KeyboardEvent} from 'react';

import type {AnalysisSummary} from '../api/types';
import type {Example} from '../lib/examples';
import {QUESTION_MAX, QUESTION_MIN} from '../lib/examples';
import {EntitiesLine} from './EntitiesLine';
import {ExampleChips} from './ExampleChips';

/** Props of QuestionArea. */
export interface QuestionAreaProps {
  readonly question: string;
  readonly onQuestionChange: (question: string) => void;
  readonly onAsk: (question: string) => void;
  /** False while busy, rate limited, offline, or without an index. */
  readonly askEnabled: boolean;
  readonly examples: readonly Example[];
  /** The analysis of the current question, for the entities line. */
  readonly analysis: AnalysisSummary | null;
}

/**
 * True when the question length is inside the API limits.
 *
 * @param question The question text.
 * @return Whether the question may be sent.
 */
export function questionValid(question: string): boolean {
  const length = question.trim().length;
  return length >= QUESTION_MIN && length <= QUESTION_MAX;
}

/**
 * The question area (chapter 14.5): the input with a character counter, the
 * example chips, the Ask button, and the resolved entities line.
 *
 * @param props The props.
 * @return The question area.
 */
export function QuestionArea({
  question,
  onQuestionChange,
  onAsk,
  askEnabled,
  examples,
  analysis,
}: QuestionAreaProps): JSX.Element {
  const valid = questionValid(question);
  const tooLong = question.trim().length > QUESTION_MAX;
  const submit = (event: FormEvent): void => {
    event.preventDefault();
    if (askEnabled && valid) {
      onAsk(question.trim());
    }
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key === 'Enter' && !event.shiftKey) {
      submit(event);
    }
  };
  return (
    <section className="space-y-3" aria-label="Question">
      <form className="space-y-2" onSubmit={submit}>
        <label htmlFor="keel-question" className="sr-only">
          Question
        </label>
        <textarea
          id="keel-question"
          rows={2}
          className="w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-base shadow-sm focus:border-accent focus:outline-none"
          placeholder="Ask about the 10-K and 10-Q filings"
          value={question}
          onChange={event => onQuestionChange(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="flex items-center gap-3">
          <span
            className={`text-xs tabular-nums ${tooLong ? 'text-red-600' : 'text-slate-500'}`}
            data-testid="char-counter"
          >
            {question.trim().length} / {QUESTION_MAX}
          </span>
          <button
            type="submit"
            className="ml-auto rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!askEnabled || !valid}
          >
            Ask
          </button>
        </div>
      </form>
      <ExampleChips
        examples={examples}
        disabled={!askEnabled}
        onPick={example => {
          onQuestionChange(example.question);
          onAsk(example.question);
        }}
      />
      <EntitiesLine analysis={analysis} />
    </section>
  );
}
