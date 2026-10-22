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
    <section className="panel" aria-label={title} data-testid={testId}>
      <div className="panel-head">
        <h2 className="panel-title">
          {title}{' '}
          <span className="ml-2 font-mono text-[10.5px] font-normal normal-case tracking-normal text-muted">
            {document.source}
          </span>
        </h2>
      </div>
      {document.markdown === null ? (
        <p
          className="panel-body text-[13px] text-muted"
          data-testid="eval-empty"
        >
          {empty}
        </p>
      ) : (
        <div className="panel-body space-y-4 overflow-x-auto">
          {splitSections(document.markdown).map((section, index) => (
            <div
              key={`${section.heading ?? ''}-${index}`}
              className="space-y-2"
            >
              {section.heading !== null &&
                (section.level <= 2 ? (
                  <h3 className="border-b border-line pb-1 font-mono text-[12px] font-semibold uppercase tracking-[0.1em] text-ink">
                    {section.heading}
                  </h3>
                ) : (
                  <h4 className="text-[13px] font-semibold text-ink">
                    {section.heading}
                  </h4>
                ))}
              {section.body !== '' && (
                <AnswerMarkdown markdown={section.body} />
              )}
            </div>
          ))}
          {document.truncated && (
            <p className="text-xs text-muted">
              The file is longer than the page shows.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
