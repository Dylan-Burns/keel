import type {JSX} from 'react';
import {useMemo} from 'react';

import {renderMarkdown} from '../lib/markdown';

/** Props of AnswerMarkdown. */
export interface AnswerMarkdownProps {
  /** The direct answer as the model wrote it (untrusted). */
  readonly markdown: string;
}

/**
 * The answer markdown: the only HTML on the page, after `marked` and
 * DOMPurify with the chapter 15 allow list (control S-03).
 *
 * @param props The props.
 * @return The rendered answer.
 */
export function AnswerMarkdown({markdown}: AnswerMarkdownProps): JSX.Element {
  const html = useMemo(() => renderMarkdown(markdown), [markdown]);
  return (
    <div
      className="answer-markdown space-y-3 leading-relaxed"
      data-testid="answer-markdown"
      // The HTML comes from renderMarkdown, which sanitizes with DOMPurify.
      dangerouslySetInnerHTML={{__html: html}}
    />
  );
}
