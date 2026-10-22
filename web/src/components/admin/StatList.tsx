import type {JSX} from 'react';

/** 1 label and value of a stat list. */
export interface Stat {
  readonly label: string;
  readonly value: string;
  /** A tone for the value: `up`, `down`, `warn`, or none. */
  readonly tone?: 'up' | 'down' | 'warn';
}

/** Props of StatList. */
export interface StatListProps {
  readonly stats: readonly Stat[];
  readonly testId?: string;
}

const TONE: Readonly<Record<NonNullable<Stat['tone']>, string>> = {
  up: 'text-up',
  down: 'text-down',
  warn: 'text-warn',
};

/**
 * A terminal-style list of labels and values, 1 per row with striped rows.
 *
 * @param props The props.
 * @return The list.
 */
export function StatList({stats, testId}: StatListProps): JSX.Element {
  return (
    <dl className="py-1 font-mono text-[11.5px]" data-testid={testId}>
      {stats.map(stat => (
        <div
          key={stat.label}
          className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] gap-3 px-3 py-[3px] odd:bg-raised"
        >
          <dt className="truncate text-muted">{stat.label}</dt>
          <dd
            className={`break-words ${stat.tone === undefined ? 'text-ink' : TONE[stat.tone]}`}
          >
            {stat.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
