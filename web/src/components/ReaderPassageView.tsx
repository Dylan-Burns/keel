import type {JSX} from 'react';

import type {ReaderPassage} from '../api/types';
import {isCitedRow, parseTable, splitQuote} from '../lib/reader';
import {ReaderTable} from './ReaderTable';

/** Props of ReaderPassageView. */
export interface ReaderPassageViewProps {
  readonly passage: ReaderPassage;
  /** The quote of the citation, for the cited passage. */
  readonly quote?: string | undefined;
}

/**
 * 1 passage of the filing reader. The cited passage gets an accent rule,
 * and its quote a `mark`: the exact text when the passage holds it, else
 * the whole passage. A table passage renders as a table. Every string is a
 * JSX text node; no filing text is ever parsed as HTML.
 *
 * @param props The props.
 * @return The passage.
 */
export function ReaderPassageView({
  passage,
  quote,
}: ReaderPassageViewProps): JSX.Element {
  const cited = passage.cited;
  const table = passage.is_table ? parseTable(passage.text) : null;
  let body: JSX.Element;
  if (table !== null) {
    const quoted = cited ? quote : undefined;
    const rowMarked = table.rows.some(row => isCitedRow(row, quoted));
    body = (
      <div {...(cited && !rowMarked ? {'data-reader-target': ''} : {})}>
        <ReaderTable table={table} quote={quoted} />
      </div>
    );
  } else if (cited) {
    const split = quote === undefined ? null : splitQuote(passage.text, quote);
    body =
      split === null ? (
        <p className="reader-text">
          <mark
            className="reader-mark"
            data-testid="reader-mark"
            data-reader-target=""
          >
            {passage.text}
          </mark>
        </p>
      ) : (
        <p className="reader-text">
          {split.before}
          <mark
            className="reader-mark"
            data-testid="reader-mark"
            data-reader-target=""
          >
            {split.match}
          </mark>
          {split.after}
        </p>
      );
  } else {
    body = <p className="reader-text">{passage.text}</p>;
  }
  return (
    <section
      className={
        cited
          ? 'reader-passage reader-passage-cited'
          : 'reader-passage text-ink-2'
      }
      data-testid="reader-passage"
      data-chunk-id={passage.chunk_id}
      data-cited={cited}
      aria-label={cited ? 'Cited passage' : undefined}
    >
      {body}
    </section>
  );
}
