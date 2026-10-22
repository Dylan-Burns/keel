import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import type {ChunkResponse} from '../api/types';
import {findChunk, findCitation, findResolved} from '../lib/citations';
import {pick, retrieval as retrievalMotion} from '../motion/presets';
import type {Run} from '../state';
import {SecLink} from './SecLink';

/** The chunk the user opened from a citation chip. */
export interface SelectedChunk {
  readonly chunkId: string;
  readonly detail: ChunkResponse | null;
  readonly error: string | null;
}

/** Props of RightPanel. */
export interface RightPanelProps {
  readonly run: Run | null;
  readonly selected: SelectedChunk | null;
  /** On a phone the panel is a drawer: open or closed. */
  readonly open: boolean;
  readonly onClose: () => void;
}

/**
 * The right panel (chapter 14.5): the opened chunk, the citation list, and
 * the retrieved chunks with scores and the collapsed near-duplicate count.
 * On a phone it is a drawer. Every string is a JSX text node.
 *
 * @param props The props.
 * @return The panel.
 */
export function RightPanel({
  run,
  selected,
  open,
  onClose,
}: RightPanelProps): JSX.Element {
  const reduced = useReducedMotion();
  const cited = run?.final?.citations_resolved ?? [];
  const retrieval = run?.retrieval ?? null;
  const top = Math.max(0.0001, ...(retrieval?.chunks.map(c => c.score) ?? [0]));
  return (
    <aside
      className={`${open ? 'fixed' : 'hidden'} panel inset-x-0 bottom-0 z-40 max-h-[80vh] overflow-y-auto shadow-2xl lg:sticky lg:top-12 lg:z-auto lg:block lg:max-h-[calc(100dvh-4.25rem)] lg:self-start lg:shadow-none`}
      aria-label="Sources"
      data-testid="right-panel"
      data-open={open}
    >
      <div className="panel-head sticky top-0 z-10">
        <h2 className="panel-title">Sources</h2>
        {retrieval !== null && (
          <span className="num text-[10.5px] text-muted">
            {cited.length} cited / {retrieval.chunks.length} retrieved
          </span>
        )}
        <button
          type="button"
          className="btn ml-auto lg:hidden"
          onClick={onClose}
        >
          Close
        </button>
      </div>
      {run === null && (
        <p className="panel-body text-xs text-muted">
          No question yet. The cited passages and the retrieved context of an
          answer appear here.
        </p>
      )}
      {selected !== null && run !== null && (
        <section
          className="m-2 border border-line border-l-[3px] border-l-accent bg-raised p-2.5"
          data-testid="selected-chunk"
        >
          <h3 className="section-title text-accent">Opened passage</h3>
          <p className="mt-1 text-[13px] font-semibold text-ink">
            {selected.detail?.filing_name ??
              findChunk(run, selected.chunkId)?.filing_name ??
              selected.chunkId}
          </p>
          <p className="num text-[11px] text-muted">
            {selected.detail?.section_title ??
              findResolved(run, selected.chunkId)?.section_title ??
              ''}{' '}
            {selected.detail?.fiscal_label ?? ''}
          </p>
          <SecLink
            className="text-xs"
            url={
              selected.detail?.sec_url ??
              findResolved(run, selected.chunkId)?.sec_url ??
              null
            }
          />
          {selected.error !== null && (
            <p className="text-xs text-down">{selected.error}</p>
          )}
          {selected.detail !== null && (
            <p className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap border-t border-line pt-2 text-xs leading-relaxed text-ink-2">
              {selected.detail.text}
            </p>
          )}
        </section>
      )}
      {cited.length > 0 && run !== null && (
        <section className="border-b border-line">
          <h3 className="section-title px-2.5 pb-1 pt-2.5">
            Citations <span className="num">({cited.length})</span>
          </h3>
          <ol className="divide-y divide-line" data-testid="citation-list">
            {cited.map(c => (
              <li
                key={c.chunk_id}
                className="px-2.5 py-2 text-xs"
                data-valid={c.valid}
              >
                <div className="font-semibold text-ink">{c.filing_name}</div>
                <div className="num text-[11px] text-muted">
                  {c.section_title}, {c.fiscal_label}
                  {c.valid ? '' : ', unverified'}
                </div>
                <SecLink url={c.sec_url} className="text-[11px]" />
                {findCitation(run, c.chunk_id) !== undefined && (
                  <blockquote className="mt-1 border-l-2 border-accent/50 pl-2 italic text-ink-2">
                    {findCitation(run, c.chunk_id)?.quote}
                  </blockquote>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
      {retrieval !== null && (
        <section>
          <h3 className="section-title px-2.5 pt-2.5">Retrieved chunks</h3>
          <p
            className="num px-2.5 pb-1.5 text-[10.5px] text-muted"
            data-testid="collapse-count"
          >
            {retrieval.chunks.length} chunks,{' '}
            {retrieval.collapsed_near_duplicates} near-duplicates collapsed,
            about {retrieval.token_estimate} tokens
          </p>
          <motion.ol
            className="divide-y divide-line border-t border-line"
            data-testid="chunk-list"
            variants={pick(retrievalMotion.list, reduced)}
            initial="hidden"
            animate="visible"
          >
            {retrieval.chunks.map(chunk => (
              <motion.li
                key={chunk.chunk_id}
                variants={pick(retrievalMotion.item, reduced)}
                className="px-2.5 py-1.5 text-xs hover:bg-raised"
                data-testid="chunk-row"
              >
                <div className="flex items-baseline gap-2 font-mono text-[11px]">
                  <span className="w-11 shrink-0 font-semibold text-accent">
                    {chunk.ticker}
                  </span>
                  <span className="shrink-0 text-ink">{chunk.form}</span>
                  <span className="shrink-0 text-ink-2">
                    {chunk.fiscal_label}
                  </span>
                  <span className="min-w-0 truncate text-muted">
                    {chunk.section}
                  </span>
                  <span className="num ml-auto text-ink">
                    {chunk.score.toFixed(2)}
                  </span>
                </div>
                <div className="meter my-1">
                  <motion.div
                    className="origin-left bg-accent"
                    variants={pick(retrievalMotion.bar, reduced)}
                    style={{width: `${Math.round((chunk.score / top) * 100)}%`}}
                  />
                </div>
                <SecLink
                  url={chunk.sec_url}
                  label={chunk.filing_name}
                  className="truncate text-[11px]"
                />
                {chunk.sec_url === null && (
                  <span className="block truncate text-[11px] text-muted">
                    {chunk.filing_name}
                  </span>
                )}
              </motion.li>
            ))}
          </motion.ol>
        </section>
      )}
    </aside>
  );
}
