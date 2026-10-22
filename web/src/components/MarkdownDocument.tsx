import type {JSX} from 'react';

import type {EvalDocument} from '../api/types';
import {AnswerMarkdown} from './AnswerMarkdown';

/** 1 section of a markdown document: its heading and its body. */
export interface MarkdownSection {
  readonly heading: string | null;
  readonly level: number;
  readonly body: string;
}

/**
 * Splits markdown at its ATX headings, so a heading renders as a JSX text
 * node and its body through the answer renderer (the chapter 15 allow list
 * holds no heading tag).
 *
 * @param markdown The document.
 * @return The sections in order; text before the first heading has none.
 */
export function splitSections(markdown: string): MarkdownSection[] {
  const sections: MarkdownSection[] = [];
  let heading: string | null = null;
  let level = 0;
  let body: string[] = [];
  let fenced = false;
  const flush = (): void => {
    const text = body.join('\n').trim();
    if (heading !== null || text !== '') {
      sections.push({heading, level, body: text});
    }
  };
  for (const line of markdown.split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) {
      fenced = !fenced;
    }
    const match = fenced ? null : /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (match !== null) {
      flush();
      heading = match[2] ?? '';
      level = match[1]?.length ?? 1;
      body = [];
    } else {
      body.push(line);
    }
  }
  flush();
  return sections;
}

/** Props of MarkdownDocument. */
export interface MarkdownDocumentProps {
  readonly title: string;
  readonly document: EvalDocument;
  readonly empty: string;
  readonly testId: string;
}

/**
 * 1 read-only markdown document of the eval page, or its empty state.
 *
 * @param props The props.
 * @return The document.
 */
export function MarkdownDocument({
  title,
  document,
  empty,
  testId,
}: MarkdownDocumentProps): JSX.Element {
  return (
    <section className="space-y-3" aria-label={title} data-testid={testId}>
      <h2 className="text-lg font-semibold">
        {title}{' '}
        <span className="font-mono text-xs font-normal text-slate-500">
          {document.source}
        </span>
      </h2>
      {document.markdown === null ? (
        <p
          className="rounded border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-600"
          data-testid="eval-empty"
        >
          {empty}
        </p>
      ) : (
        <div className="space-y-4 overflow-x-auto">
          {splitSections(document.markdown).map((section, index) => (
            <div
              key={`${section.heading ?? ''}-${index}`}
              className="space-y-2"
            >
              {section.heading !== null &&
                (section.level <= 2 ? (
                  <h3 className="text-base font-semibold">{section.heading}</h3>
                ) : (
                  <h4 className="text-sm font-semibold">{section.heading}</h4>
                ))}
              {section.body !== '' && (
                <AnswerMarkdown markdown={section.body} />
              )}
            </div>
          ))}
          {document.truncated && (
            <p className="text-xs text-slate-500">
              The file is longer than the page shows.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
