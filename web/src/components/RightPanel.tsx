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
      className={`${open ? 'fixed' : 'hidden'} inset-x-0 bottom-0 z-20 max-h-[80vh] overflow-y-auto rounded-t-2xl border-t border-slate-200 bg-white p-4 shadow-2xl lg:static lg:block lg:max-h-none lg:rounded-none lg:border-l lg:border-t-0 lg:shadow-none`}
      aria-label="Sources"
      data-testid="right-panel"
      data-open={open}
    >
      <div className="mb-2 flex items-center lg:hidden">
        <h2 className="font-medium">Sources</h2>
        <button
          type="button"
          className="ml-auto text-sm text-slate-600 underline"
          onClick={onClose}
        >
          Close
        </button>
      </div>
      {selected !== null && run !== null && (
        <section
          className="mb-4 rounded-lg border border-accent/40 bg-accent/5 p-3"
          data-testid="selected-chunk"
        >
          <h3 className="text-sm font-medium">
            {selected.detail?.filing_name ??
              findChunk(run, selected.chunkId)?.filing_name ??
              selected.chunkId}
          </h3>
          <p className="text-xs text-slate-600">
            {selected.detail?.section_title ??
              findResolved(run, selected.chunkId)?.section_title ??
              ''}{' '}
            {selected.detail?.fiscal_label ?? ''}
          </p>
          <SecLink
            url={
              selected.detail?.sec_url ??
              findResolved(run, selected.chunkId)?.sec_url ??
              null
            }
          />
          {selected.error !== null && (
            <p className="text-xs text-red-700">{selected.error}</p>
          )}
          {selected.detail !== null && (
            <p className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-slate-800">
              {selected.detail.text}
            </p>
          )}
        </section>
      )}
      {cited.length > 0 && run !== null && (
        <section className="mb-4">
          <h2 className="mb-2 text-sm font-medium">Citations</h2>
          <ol className="space-y-2" data-testid="citation-list">
            {cited.map(c => (
              <li
                key={c.chunk_id}
                className="rounded border border-slate-200 p-2 text-xs"
                data-valid={c.valid}
              >
                <div className="font-medium">{c.filing_name}</div>
                <div className="text-slate-600">
                  {c.section_title}, {c.fiscal_label}
                  {c.valid ? '' : ', unverified'}
                </div>
                <SecLink url={c.sec_url} />
                {findCitation(run, c.chunk_id) !== undefined && (
                  <blockquote className="mt-1 border-l-2 border-slate-300 pl-2 italic text-slate-700">
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
          <h2 className="mb-1 text-sm font-medium">Retrieved chunks</h2>
          <p
            className="mb-2 text-xs text-slate-500"
            data-testid="collapse-count"
          >
            {retrieval.chunks.length} chunks,{' '}
            {retrieval.collapsed_near_duplicates} near-duplicates collapsed,
            about {retrieval.token_estimate} tokens
          </p>
          <motion.ol
            className="space-y-1"
            data-testid="chunk-list"
            variants={pick(retrievalMotion.list, reduced)}
            initial="hidden"
            animate="visible"
          >
            {retrieval.chunks.map(chunk => (
              <motion.li
                key={chunk.chunk_id}
                variants={pick(retrievalMotion.item, reduced)}
                className="text-xs"
                data-testid="chunk-row"
              >
                <div className="flex items-baseline gap-2">
                  <span className="font-mono">{chunk.ticker}</span>
                  <span>{chunk.form}</span>
                  <span>{chunk.fiscal_label}</span>
                  <span className="text-slate-500">{chunk.section}</span>
                  <span className="ml-auto tabular-nums">
                    {chunk.score.toFixed(2)}
                  </span>
                </div>
                <div className="h-1 rounded bg-slate-100">
                  <motion.div
                    className="h-1 origin-left rounded bg-accent"
                    variants={pick(retrievalMotion.bar, reduced)}
                    style={{width: `${Math.round((chunk.score / top) * 100)}%`}}
                  />
                </div>
                <SecLink url={chunk.sec_url} label={chunk.filing_name} />
                {chunk.sec_url === null && (
                  <span className="text-slate-600">{chunk.filing_name}</span>
                )}
              </motion.li>
            ))}
          </motion.ol>
        </section>
      )}
    </aside>
  );
}
