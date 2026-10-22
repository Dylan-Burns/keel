import type {JSX, ReactNode} from 'react';

import type {ResponseMeta} from '../api/types';
import type {Health} from '../state';

/** Props of TopBar. */
export interface TopBarProps {
  readonly indexVersion: string | null;
  readonly health: Health;
  /** The meta of the last answer, for the latency and cost badge. */
  readonly lastMeta: ResponseMeta | null;
  /** The token field. */
  readonly children?: ReactNode;
}

const DOT: Readonly<Record<Health, string>> = {
  green: 'bg-emerald-500',
  amber: 'bg-amber-400',
  red: 'bg-red-500',
  unknown: 'bg-slate-300',
};

/**
 * Formats the latency and cost badge text.
 *
 * @param latencyMs The total latency in milliseconds.
 * @param costUsd The cost in US dollars.
 * @return The badge text, such as `18.4 s, $0.082`.
 */
export function badgeText(latencyMs: number, costUsd: number): string {
  return `${(latencyMs / 1000).toFixed(1)} s, $${costUsd.toFixed(3)}`;
}

/**
 * The top bar (chapter 14.5): the name, the index version badge, the health
 * dot, and the latency and cost badge of the last answer.
 *
 * @param props The props.
 * @return The top bar.
 */
export function TopBar({
  indexVersion,
  health,
  lastMeta,
  children,
}: TopBarProps): JSX.Element {
  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
      <h1 className="text-2xl font-semibold tracking-tight text-accent">
        Keel
      </h1>
      <span
        className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
        data-testid="index-version"
      >
        index {indexVersion ?? 'unknown'}
      </span>
      <span
        className={`inline-block h-2.5 w-2.5 rounded-full ${DOT[health]}`}
        data-testid="health-dot"
        data-health={health}
        role="img"
        aria-label={`Service health: ${health}`}
      />
      {lastMeta !== null && (
        <span
          className="rounded bg-slate-100 px-2 py-0.5 text-xs tabular-nums text-slate-700"
          data-testid="cost-badge"
          data-final={badgeText(lastMeta.latency_ms.total, lastMeta.cost_usd)}
        >
          {badgeText(lastMeta.latency_ms.total, lastMeta.cost_usd)}
        </span>
      )}
      <div className="ml-auto">{children}</div>
    </header>
  );
}
