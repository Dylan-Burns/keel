import type {JSX} from 'react';

import type {DiffToken, PartChange} from '../../lib/promptDiff';
import {wordDiff} from '../../lib/promptDiff';

/** Props of RuleChange. */
export interface RuleChangeProps {
  readonly change: PartChange;
  readonly from: string;
  readonly to: string;
}

/** The words of 1 side of a diff: the kept words and its own changes. */
function Side({
  tokens,
  side,
}: {
  readonly tokens: readonly DiffToken[];
  readonly side: 'before' | 'after';
}): JSX.Element {
  const runs: {op: DiffToken['op']; text: string}[] = [];
  for (const token of tokens) {
    if (side === 'before' ? token.op === 'add' : token.op === 'del') {
      continue;
    }
    const last = runs[runs.length - 1];
    if (last !== undefined && last.op === token.op) {
      last.text = `${last.text} ${token.text}`;
    } else {
      runs.push({op: token.op, text: token.text});
    }
  }
  return (
    <p className="leading-relaxed text-ink-2">
      {runs.map((run, index) => {
        const space = index === 0 ? '' : ' ';
        if (run.op === 'same') {
          return `${space}${run.text}`;
        }
        return side === 'before' ? (
          <span key={index}>
            {space}
            <del className="rounded-[2px] bg-down/15 text-ink decoration-down/70">
              {run.text}
            </del>
          </span>
        ) : (
          <span key={index}>
            {space}
            <ins className="rounded-[2px] bg-up/20 text-ink no-underline">
              {run.text}
            </ins>
          </span>
        );
      })}
    </p>
  );
}

/**
 * 1 rule before and after a prompt change, side by side, with the removed
 * words struck through on the left and the added words marked on the
 * right. A new rule shows only its text; a removed rule only its old text.
 *
 * @param props The change and the 2 version names.
 * @return The comparison.
 */
export function RuleChange({change, from, to}: RuleChangeProps): JSX.Element {
  const tokens =
    change.kind === 'changed'
      ? wordDiff(change.before ?? '', change.after ?? '')
      : [];
  return (
    <div
      className="rounded-sm border border-line text-[12.5px]"
      data-testid="rule-change"
      data-kind={change.kind}
    >
      <div className="flex items-center gap-2 border-b border-line bg-raised px-2.5 py-1">
        <span className="font-mono text-[11.5px] font-semibold text-ink">
          {change.label}
        </span>
        {change.kind !== 'changed' && (
          <span className="tag">
            {change.kind === 'added' ? `New in ${to}` : `Removed in ${to}`}
          </span>
        )}
      </div>
      {change.kind === 'changed' ? (
        <div className="grid divide-line md:grid-cols-2 md:divide-x">
          <div className="space-y-1 px-2.5 py-2">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted">
              Before ({from})
            </div>
            <Side tokens={tokens} side="before" />
          </div>
          <div className="space-y-1 px-2.5 py-2">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted">
              After ({to})
            </div>
            <Side tokens={tokens} side="after" />
          </div>
        </div>
      ) : (
        <p className="px-2.5 py-2 leading-relaxed text-ink-2">
          {change.after ?? change.before}
        </p>
      )}
    </div>
  );
}
