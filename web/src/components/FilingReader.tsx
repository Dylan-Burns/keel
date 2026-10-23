import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';
import {useEffect, useRef, useState} from 'react';

import {fetchChunkContext} from '../api/client';
import type {ChunkContext} from '../api/types';
import {citationLink} from '../lib/fragment';
import {filingReader, pick} from '../motion/presets';
import {LocationLines} from './LocationLines';
import {ReaderPassageView} from './ReaderPassageView';
import {SecLink} from './SecLink';

/** Props of FilingReader. */
export interface FilingReaderProps {
  /** The cited chunk to show. */
  readonly chunkId: string;
  /** The cited chunk IDs of the answer, in order, for previous and next. */
  readonly order: readonly string[];
  /** The quote of a cited chunk, if the answer has one. */
  readonly quoteFor: (chunkId: string) => string | undefined;
  /** Shows another cited chunk: previous or next. */
  readonly onNavigate: (chunkId: string) => void;
  /** Closes the reader. */
  readonly onClose: () => void;
}

/** What the reader holds for the chunk it shows. */
interface Loaded {
  readonly chunkId: string;
  readonly context: ChunkContext | null;
  readonly error: string | null;
}

/**
 * The filing reader: the cited section of the filing from Keel's own index,
 * the cited passage marked and scrolled into view, with the filing header,
 * the section label, the SEC deep link, and previous and next citation.
 * No model call; the text is the chunk text, rendered as JSX text nodes.
 *
 * @param props The props.
 * @return The reader dialog.
 */
export function FilingReader({
  chunkId,
  order,
  quoteFor,
  onNavigate,
  onClose,
}: FilingReaderProps): JSX.Element {
  const reduced = useReducedMotion();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const body = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);

  // Focus moves into the dialog on open and back to the opener on close.
  useEffect(() => {
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    close.current?.focus();
    return () => opener?.focus();
  }, []);

  useEffect(() => {
    let live = true;
    fetchChunkContext(chunkId)
      .then(context => {
        if (live) {
          setLoaded({chunkId, context, error: null});
        }
      })
      .catch(() => {
        if (live) {
          setLoaded({
            chunkId,
            context: null,
            error: 'The filing text could not be loaded.',
          });
        }
      });
    return () => {
      live = false;
    };
  }, [chunkId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      // Tab stays inside the modal dialog.
      const box = dialog.current;
      if (event.key !== 'Tab' || box === null) {
        return;
      }
      const items = Array.from(
        box.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      const first = items[0];
      const last = items.at(-1);
      if (first === undefined || last === undefined) {
        return;
      }
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const current = loaded?.chunkId === chunkId ? loaded : null;
  const context = current?.context ?? null;

  useEffect(() => {
    if (context === null) {
      return;
    }
    const box = body.current;
    const target = box?.querySelector('[data-reader-target]');
    if (
      box === null ||
      box === undefined ||
      !(target instanceof HTMLElement) ||
      typeof box.scrollTo !== 'function'
    ) {
      return;
    }
    // Vertical only: a wide table must not scroll the text sideways.
    const offset =
      target.getBoundingClientRect().top - box.getBoundingClientRect().top;
    const top =
      box.scrollTop +
      offset -
      (box.clientHeight - target.getBoundingClientRect().height) / 2;
    box.scrollTo({
      top: Math.max(0, top),
      behavior: reduced === true ? 'auto' : 'smooth',
    });
  }, [context, reduced]);

  const index = order.indexOf(chunkId);
  const previous = index > 0 ? order[index - 1] : undefined;
  const next =
    index >= 0 && index < order.length - 1 ? order[index + 1] : undefined;
  const quote = quoteFor(chunkId);
  const filing = context?.filing ?? null;

  return (
    <motion.div
      className="fixed inset-0 z-50 flex justify-end bg-canvas/70"
      variants={pick(filingReader.backdrop, reduced)}
      initial="hidden"
      animate="visible"
      exit="exit"
      onClick={event => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
      data-testid="filing-reader-backdrop"
    >
      <motion.div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="filing-reader-title"
        className="panel flex h-full w-full min-w-0 max-w-3xl flex-col shadow-2xl"
        variants={pick(filingReader.panel, reduced)}
        data-testid="filing-reader"
        data-chunk-id={chunkId}
        data-loaded={context !== null}
      >
        <header className="panel-head flex-wrap gap-y-1.5 border-b border-line">
          <h2
            id="filing-reader-title"
            className="min-w-0 truncate text-[13px] font-semibold text-ink"
          >
            {filing?.filing_name ?? 'Filing reader'}
          </h2>
          <div className="ml-auto flex items-center gap-1.5">
            <button
              type="button"
              className="btn"
              disabled={previous === undefined}
              onClick={() => previous !== undefined && onNavigate(previous)}
              data-testid="reader-previous"
            >
              Previous
            </button>
            <span className="num text-[10.5px] text-muted">
              {index >= 0 ? `${index + 1} of ${order.length}` : ''}
            </span>
            <button
              type="button"
              className="btn"
              disabled={next === undefined}
              onClick={() => next !== undefined && onNavigate(next)}
              data-testid="reader-next"
            >
              Next
            </button>
            <button
              ref={close}
              type="button"
              className="btn"
              onClick={onClose}
              data-testid="reader-close"
            >
              Close
            </button>
          </div>
        </header>
        <div
          className="border-b border-line bg-raised px-3 py-2 text-xs"
          data-testid="reader-header"
        >
          {filing !== null && (
            <p className="text-[11px] text-muted">
              {filing.company} ({filing.ticker}), {filing.form},{' '}
              {filing.fiscal_label}, period ended {filing.period_end}
            </p>
          )}
          <LocationLines
            location={context?.location ?? null}
            fallback={filing === null ? 'Loading the filing text' : ''}
            filingDate={filing?.filing_date}
          />
          {filing !== null && (
            <SecLink
              className="text-[11px]"
              url={citationLink(
                filing.sec_url,
                quote ?? '',
                context?.location ?? null,
              )}
            />
          )}
        </div>
        <div
          ref={body}
          className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-3 py-3"
          data-testid="reader-body"
        >
          {current?.error !== null && current?.error !== undefined && (
            <p className="text-xs text-down">{current.error}</p>
          )}
          {context === null && current === null && (
            <p className="text-xs text-muted">Loading the filing text.</p>
          )}
          {context?.passages.map(passage => (
            <ReaderPassageView
              key={passage.chunk_id}
              passage={passage}
              quote={passage.cited ? quote : undefined}
            />
          ))}
          {context !== null && (
            <p className="mt-3 text-[10.5px] text-muted">
              The text of the filing as Keel indexed it; adjacent passages share
              a few sentences, shown once.
            </p>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}
