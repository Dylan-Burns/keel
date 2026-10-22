import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';
import {useMemo} from 'react';

import {markdownBlocks, renderMarkdown} from '../lib/markdown';
import {pick, stream} from '../motion/presets';

/** Props of AnswerMarkdown. */
export interface AnswerMarkdownProps {
  /** The direct answer as the model wrote it so far (untrusted). */
  readonly markdown: string;
  /** True while the answer streams: the cursor blinks after the text. */
  readonly streaming?: boolean;
}

/**
 * The answer markdown: the only HTML on the page, after `marked` and
 * DOMPurify with the chapter 15 allow list (control S-03). The same element
 * renders the answer while it streams and once it is final, 1 child per
 * markdown block keyed by its position: a finished block keeps its DOM node
 * and fades in once, and only the last block grows as deltas arrive.
 *
 * @param props The props.
 * @return The rendered answer.
 */
export function AnswerMarkdown({
  markdown,
  streaming = false,
}: AnswerMarkdownProps): JSX.Element {
  const reduced = useReducedMotion();
  const blocks = useMemo(
    () => markdownBlocks(markdown).map(block => renderMarkdown(block)),
    [markdown],
  );
  return (
    <div
      className="answer-markdown"
      data-testid="answer-markdown"
      data-streaming={streaming}
      data-blocks={blocks.length}
      aria-live={streaming ? 'polite' : undefined}
      aria-busy={streaming}
    >
      {blocks.map((html, index) => (
        <motion.div
          // A block's position is its identity: the streamed text only
          // appends, so a key never moves to another block.
          key={index}
          className="answer-block"
          data-testid="answer-block"
          variants={pick(stream.section, reduced)}
          initial="hidden"
          animate="visible"
          // The HTML comes from renderMarkdown, which sanitizes with DOMPurify.
          dangerouslySetInnerHTML={{__html: html}}
        />
      ))}
      {streaming && (
        <motion.span
          variants={pick(stream.cursor, reduced)}
          initial="hidden"
          animate="visible"
          className="answer-cursor"
          data-testid="answer-cursor"
          aria-hidden="true"
        />
      )}
    </div>
  );
}
