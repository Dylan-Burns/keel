import type {JSX} from 'react';

import type {AnalysisSummary} from '../api/types';

/** Props of EntitiesLine. */
export interface EntitiesLineProps {
  readonly analysis: AnalysisSummary | null;
}

/**
 * The resolved entities line, with a did-you-mean note after a fuzzy match.
 *
 * @param props The props.
 * @return The line, or nothing before the analysis.
 */
export function EntitiesLine({
  analysis,
}: EntitiesLineProps): JSX.Element | null {
  if (analysis === null || analysis.tickers.length === 0) {
    return null;
  }
  const fuzzy = (analysis.entities ?? []).filter(e => e.fuzzy === true);
  return (
    <div
      className="flex flex-wrap items-center gap-2 text-sm"
      data-testid="entities-line"
    >
      <span className="text-slate-500">Companies:</span>
      {analysis.tickers.map(ticker => (
        <span
          key={ticker}
          className="rounded bg-slate-800 px-2 py-0.5 font-mono text-xs text-white"
          data-testid="entity-chip"
        >
          {ticker}
        </span>
      ))}
      {fuzzy.map(e => (
        <span key={e.text} className="text-xs text-slate-500">
          Did you mean {e.company}? (read &quot;{e.text}&quot; as {e.ticker})
        </span>
      ))}
    </div>
  );
}
