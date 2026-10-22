import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import type {AnalysisSummary} from '../api/types';
import {entitiesResolved, pick} from '../motion/presets';

/** Props of EntitiesLine. */
export interface EntitiesLineProps {
  readonly analysis: AnalysisSummary | null;
}

/**
 * The resolved entities line, with a did-you-mean note after a fuzzy match
 * and a note per comp set the question names (chapter 27.2).
 *
 * @param props The props.
 * @return The line, or nothing before the analysis.
 */
export function EntitiesLine({
  analysis,
}: EntitiesLineProps): JSX.Element | null {
  const reduced = useReducedMotion();
  if (analysis === null || analysis.tickers.length === 0) {
    return null;
  }
  const fuzzy = (analysis.entities ?? []).filter(e => e.fuzzy === true);
  return (
    <motion.div
      className="flex flex-wrap items-center gap-2 text-sm"
      data-testid="entities-line"
      variants={pick(entitiesResolved.chips, reduced)}
      initial="hidden"
      animate="visible"
    >
      <span className="text-slate-500">Companies:</span>
      {analysis.tickers.map(ticker => (
        <motion.span
          key={ticker}
          variants={pick(entitiesResolved.chip, reduced)}
          className="rounded bg-slate-800 px-2 py-0.5 font-mono text-xs text-white"
          data-testid="entity-chip"
        >
          {ticker}
        </motion.span>
      ))}
      {(analysis.comp_sets ?? []).map(set => (
        <span
          key={set.name}
          className="text-xs text-slate-500"
          data-testid="comp-set-note"
        >
          {`"${set.text}" is the comp set ${set.name}`}
          {set.missing.length > 0 &&
            `; not in the index: ${set.missing.join(', ')}`}
        </span>
      ))}
      {fuzzy.map(e => (
        <span key={e.text} className="text-xs text-slate-500">
          Did you mean {e.company}? (read &quot;{e.text}&quot; as {e.ticker})
        </span>
      ))}
    </motion.div>
  );
}
