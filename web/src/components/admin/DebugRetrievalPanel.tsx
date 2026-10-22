import type {JSX} from 'react';

import type {DebugRetrieval} from '../../api/types';
import {OpsPanelHead} from './OpsPanelHead';
import type {Stat} from './StatList';
import {StatList} from './StatList';

/** Props of DebugRetrievalPanel. */
export interface DebugRetrievalPanelProps {
  readonly retrieval: DebugRetrieval;
}

/**
 * The retrieval of `keel retrieve --summary`: the sub-queries with their
 * terms, the counts, the quota fills, the timings, and the chunks of the
 * context with their rerank score as a bar.
 *
 * @param props The props.
 * @return The panel.
 */
export function DebugRetrievalPanel({
  retrieval,
}: DebugRetrievalPanelProps): JSX.Element {
  const {context, timings_ms: timings} = retrieval;
  const items = context.items;
  const top = Math.max(...items.map(item => item.score ?? 0), 1e-9);
  const stats: Stat[] = [
    {
      label: 'candidates',
      value: `${retrieval.candidates} gathered, ${retrieval.collapsed} near-duplicates collapsed, ${retrieval.reranked} reranked`,
    },
    {
      label: 'context',
      value: `${context.chunks} chunks of ${context.max_chunks}, ${context.token_estimate} of ${context.max_tokens} tokens, ${context.dropped} dropped`,
    },
    ...retrieval.fills.map(fill => ({
      label: `quota ${fill.label}`,
      value: `${fill.taken} of ${fill.quota} from ${fill.candidates} candidates, ${fill.tokens} tokens`,
    })),
    {
      label: 'timings',
      value: Object.entries(timings)
        .map(([stage, ms]) => `${stage} ${ms.toFixed(0)} ms`)
        .join(', '),
    },
  ];
  if (retrieval.gaps.length > 0) {
    stats.push({label: 'gaps', value: retrieval.gaps.join('; '), tone: 'warn'});
  }
  if (retrieval.degraded.length > 0) {
    stats.push({
      label: 'degraded',
      value: retrieval.degraded.join('; '),
      tone: 'warn',
    });
  }
  return (
    <section
      className="panel"
      aria-label="Retrieval"
      data-testid="debug-retrieval"
    >
      <OpsPanelHead title="Retrieval" note="keel retrieve --summary" />
      <ol className="divide-y divide-line border-b border-line">
        {retrieval.sub_queries.map(query => (
          <li
            key={query.label}
            className="space-y-1 px-3 py-2 text-[12px]"
            data-testid="debug-subquery"
          >
            <p className="font-mono text-[11px] font-semibold text-accent">
              {query.label}
            </p>
            <p className="text-ink">{query.dense_text}</p>
            <p className="flex flex-wrap gap-1">
              {query.terms.map(term => (
                <span key={term} className="tag">
                  {term}
                </span>
              ))}
            </p>
          </li>
        ))}
      </ol>
      <StatList stats={stats} testId="debug-counts" />
      <h3 className="section-title border-t border-line px-3 pb-1 pt-2.5">
        Context chunks <span className="num">({items.length})</span>
      </h3>
      <ol
        className="divide-y divide-line border-t border-line"
        data-testid="debug-chunks"
      >
        {items.map(item => (
          <li
            key={item.chunk_id}
            className="px-3 py-1.5 text-xs hover:bg-raised"
            data-testid="debug-chunk"
          >
            <div className="flex flex-wrap items-baseline gap-x-2 font-mono text-[11px]">
              <span className="w-11 shrink-0 font-semibold text-accent">
                {item.ticker}
              </span>
              <span className="shrink-0 text-ink">{item.form}</span>
              <span className="shrink-0 text-ink-2">
                {item.period_end_date ?? ''}
              </span>
              <span className="min-w-0 truncate text-muted">
                {item.section}
              </span>
              <span className="num ml-auto text-muted">
                {item.estimated_tokens} tok{item.truncated ? ', cut' : ''}
              </span>
              <span className="num w-12 text-right text-ink">
                {item.score === undefined ? '--' : item.score.toFixed(2)}
              </span>
            </div>
            <div className="meter my-1">
              <div
                className="bg-accent"
                style={{
                  width: `${Math.max(0, Math.round(((item.score ?? 0) / top) * 100))}%`,
                }}
              />
            </div>
            <p className="truncate font-mono text-[10.5px] text-muted">
              {item.chunk_id}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
