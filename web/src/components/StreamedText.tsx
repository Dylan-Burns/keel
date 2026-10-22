import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import {pick, stream} from '../motion/presets';

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
  const reduced = useReducedMotion();
  return (
    <p
      className="whitespace-pre-wrap leading-relaxed"
      data-testid="streamed-answer"
      data-deltas={deltas.length}
      aria-live="polite"
    >
      {deltas.map((text, index) => (
        <motion.span
          key={index}
          variants={pick(stream.delta, reduced)}
          initial="hidden"
          animate="visible"
        >
          {text}
        </motion.span>
      ))}
      <motion.span
        variants={pick(stream.cursor, reduced)}
        initial="hidden"
        animate="visible"
        className="answer-cursor ml-0.5 inline-block w-2 text-accent"
        aria-hidden="true"
      >
        |
      </motion.span>
    </p>
  );
}
