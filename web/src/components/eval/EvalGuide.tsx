import type {JSX} from 'react';

import type {SectionGuide} from '../../lib/evalGuide';

/** Props of EvalGuide. */
export interface EvalGuideProps {
  readonly guide: SectionGuide;
}

/**
 * The plain-language note under a section of the eval report: what the
 * section shows, what good looks like, and each column. Open by default;
 * a reader who knows the report can fold it.
 *
 * @param props The note.
 * @return The note.
 */
export function EvalGuide({guide}: EvalGuideProps): JSX.Element {
  return (
    <details
      open
      className="group rounded-sm border border-line bg-raised text-[12.5px]"
      data-testid="eval-guide"
    >
      <summary className="cursor-pointer select-none px-3 py-1.5 font-mono text-[10.5px] uppercase tracking-[0.1em] text-ink-2 hover:text-accent">
        What this section shows
      </summary>
      <div className="space-y-2 border-t border-line px-3 py-2.5">
        <p className="text-ink">{guide.summary}</p>
        {guide.good !== undefined && (
          <p className="text-ink-2">
            <span className="font-semibold text-ink">Good result: </span>
            {guide.good}
          </p>
        )}
        <dl className="grid gap-x-4 gap-y-1.5 sm:grid-cols-[max-content_1fr]">
          {guide.terms.map(([term, meaning]) => (
            <div key={term} className="contents">
              <dt className="whitespace-nowrap font-mono text-[11.5px] font-semibold text-ink">
                {term}
              </dt>
              <dd className="text-ink-2">{meaning}</dd>
            </div>
          ))}
        </dl>
      </div>
    </details>
  );
}
