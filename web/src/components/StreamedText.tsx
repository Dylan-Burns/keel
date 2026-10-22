import type {JSX} from 'react';

/** Props of StreamedText. */
export interface StreamedTextProps {
  /** The `answer_delta` texts in arrival order (untrusted model text). */
  readonly deltas: readonly string[];
}

/**
 * The direct answer while it streams: each delta is a JSX text node, never
 * HTML, followed by the cursor.
 *
 * @param props The props.
 * @return The growing answer.
 */
export function StreamedText({deltas}: StreamedTextProps): JSX.Element {
  return (
    <p
      className="whitespace-pre-wrap leading-relaxed"
      data-testid="streamed-answer"
      data-deltas={deltas.length}
      aria-live="polite"
    >
      {deltas.map((text, index) => (
        <span key={index}>{text}</span>
      ))}
      <span
        className="answer-cursor ml-0.5 inline-block w-2 text-accent"
        aria-hidden="true"
      >
        |
      </span>
    </p>
  );
}
