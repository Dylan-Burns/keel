import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';
import {useEffect, useMemo, useRef} from 'react';

import {fallbackChip} from '../lib/citations';
import type {CitationChipView} from '../lib/markdown';
import {
  chipCitations,
  markdownBlocks,
  renderMarkdown,
  tagCitations,
  trimPartialCitation,
} from '../lib/markdown';
import {pick, stream} from '../motion/presets';

/** Props of AnswerMarkdown. */
export interface AnswerMarkdownProps {
  /** The direct answer as the model wrote it so far (untrusted). */
  readonly markdown: string;
  /** True while the answer streams: the cursor blinks after the text. */
  readonly streaming?: boolean;
  /**
   * The chip of a cited ID. Without it, the chip label comes from the ID
   * alone (ticker, form, and year), never the raw ID.
   */
  readonly resolveCitation?: (chunkId: string) => CitationChipView;
  /** False until the `final` event: the inline chips are disabled then. */
  readonly citationsClickable?: boolean;
  /** Opens a cited source in the sources panel. */
  readonly onSelectCitation?: (chunkId: string) => void;
}

/**
 * The chip of an ID read from the ID alone.
 *
 * @param chunkId The cited ID.
 * @return The chip view.
 */
function resolveFromId(chunkId: string): CitationChipView {
  return {...fallbackChip(chunkId), valid: true};
}

/**
 * The answer markdown: the only HTML on the page, after `marked` and
 * DOMPurify with the chapter 15 allow list (control S-03). The same element
 * renders the answer while it streams and once it is final, 1 child per
 * markdown block keyed by its position: a finished block keeps its DOM node
 * and fades in once, and only the last block grows as deltas arrive. Each
 * cited ID shows as a compact chip, the same label as the finding chips;
 * a click on a chip opens the source like a finding chip does.
 *
 * @param props The props.
 * @return The rendered answer.
 */
export function AnswerMarkdown({
  markdown,
  streaming = false,
  resolveCitation = resolveFromId,
  citationsClickable = false,
  onSelectCitation,
}: AnswerMarkdownProps): JSX.Element {
  const reduced = useReducedMotion();
  const blocks = useMemo(() => {
    const text = streaming ? trimPartialCitation(markdown) : markdown;
    return markdownBlocks(text).map(block =>
      chipCitations(
        renderMarkdown(tagCitations(block)),
        resolveCitation,
        citationsClickable,
      ),
    );
  }, [markdown, streaming, resolveCitation, citationsClickable]);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // The chips are native buttons inside the sanitized HTML: they take the
    // focus and the keyboard themselves, and their clicks bubble up here.
    const element = root.current;
    if (element === null || onSelectCitation === undefined) {
      return undefined;
    }
    const onClick = (event: Event): void => {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      const chunkId = target
        .closest('button[data-chunk-id]')
        ?.getAttribute('data-chunk-id');
      if (chunkId !== undefined && chunkId !== null && chunkId !== '') {
        onSelectCitation(chunkId);
      }
    };
    element.addEventListener('click', onClick);
    return () => element.removeEventListener('click', onClick);
  }, [onSelectCitation]);
  return (
    <div
      ref={root}
      className="answer-markdown"
      data-testid="answer-markdown"
      data-streaming={streaming}
      data-blocks={blocks.length}
      aria-live="polite"
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
          // The HTML comes from renderMarkdown, which sanitizes with
          // DOMPurify; chipCitations then adds chips through the DOM API.
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
