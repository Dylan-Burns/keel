import type {FormEvent, JSX, KeyboardEvent} from 'react';

import type {AnalysisSummary} from '../api/types';
import type {Example} from '../lib/examples';
import {ADVERSARIAL, QUESTION_MAX, QUESTION_MIN} from '../lib/examples';
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
 * example chips with the G-27 preset (W-04), the Ask button, and the resolved
 * entities line.
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
    <section className="space-y-2.5" aria-label="Question">
      <form
        className="flex items-stretch border border-line-strong bg-field focus-within:border-accent focus-within:shadow-[0_0_0_1px_var(--k-accent)]"
        onSubmit={submit}
      >
        <span
          className="select-none pl-3 pt-[0.4rem] font-mono text-[15px] font-bold text-accent"
          aria-hidden="true"
        >
          &gt;
        </span>
        <label htmlFor="keel-question" className="sr-only">
          Question
        </label>
        <textarea
          id="keel-question"
          rows={2}
          className="min-h-[3.5rem] min-w-0 flex-1 resize-y bg-transparent px-2 py-2 font-mono text-[13.5px] leading-snug text-ink focus:outline-none"
          placeholder="Ask about the 10-K and 10-Q filings"
          value={question}
          onChange={event => onQuestionChange(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="flex shrink-0 flex-col items-end justify-between gap-1 border-l border-line bg-head px-2 py-1.5">
          <span
            className={`num text-[10.5px] ${tooLong ? 'text-down' : 'text-muted'}`}
            data-testid="char-counter"
          >
            {question.trim().length} / {QUESTION_MAX}
          </span>
          <button
            type="submit"
            className="btn btn-primary px-4"
            disabled={!askEnabled || !valid}
          >
            Ask
          </button>
        </div>
      </form>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="section-title mr-1">Examples</span>
        <ExampleChips
          examples={examples}
          disabled={!askEnabled}
          onPick={example => {
            onQuestionChange(example.question);
            onAsk(example.question);
          }}
        />
        <button
          type="button"
          className="chip border-dashed border-down text-down hover:border-down"
          data-testid="adversarial-preset"
          title={ADVERSARIAL.question}
          onClick={() => onQuestionChange(ADVERSARIAL.question)}
        >
          {ADVERSARIAL.label}
        </button>
      </div>
      <EntitiesLine analysis={analysis} />
    </section>
  );
}
