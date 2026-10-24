import type {JSX, ReactNode} from 'react';

import type {ResponseMeta} from '../api/types';
import type {Health} from '../state';
import {BrandLink} from './BrandLink';
import {CostBadge} from './CostBadge';
import {ThemeToggle} from './ThemeToggle';

/** Props of TopBar. */
export interface TopBarProps {
  readonly indexVersion: string | null;
  readonly health: Health;
  /** The meta of the last answer, for the latency and cost badge. */
  readonly lastMeta: ResponseMeta | null;
  /** The model requests of the last answer (its audit record), or null. */
  readonly modelRequests?: number | null;
  /** The token field. */
  readonly children?: ReactNode;
  /** The page links, as a row under the strip. */
  readonly nav?: ReactNode;
}

const DOT: Readonly<Record<Health, string>> = {
  green: 'bg-up',
  amber: 'bg-warn',
  red: 'bg-down',
  unknown: 'bg-line-strong',
};

const STATUS: Readonly<Record<Health, string>> = {
  green: 'ready',
  amber: 'degraded',
  red: 'offline',
  unknown: 'connecting',
};

const STATUS_COLOR: Readonly<Record<Health, string>> = {
  green: 'text-up',
  amber: 'text-warn',
  red: 'text-down',
  unknown: 'text-muted',
};

/**
 * The top bar (chapter 14.5) as a market-status strip: the name, the service
 * state with its health dot, the index version, the model requests and the
 * latency and cost badge of the last answer, the theme toggle, the token
 * field, and the page links under it.
 *
 * @param props The props.
 * @return The top bar.
 */
export function TopBar({
  indexVersion,
  health,
  lastMeta,
  modelRequests = null,
  children,
  nav,
}: TopBarProps): JSX.Element {
  return (
    <header className="border-b border-line bg-panel">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-3 py-1.5">
        <div className="flex items-center gap-2">
          <h1>
            <BrandLink />
          </h1>
          <span className="hidden font-mono text-[10px] uppercase tracking-[0.14em] text-muted md:inline">
            SEC filings desk
          </span>
        </div>
        <div
          className="flex flex-wrap items-center gap-x-4 gap-y-1 sm:border-l sm:border-line sm:pl-4"
          role="group"
          aria-label="Service status"
          data-testid="status-strip"
        >
          <span className="stat">
            <span
              className={`inline-block h-2 w-2 rounded-full ${DOT[health]}`}
              data-testid="health-dot"
              data-health={health}
              role="img"
              aria-label={`Service health: ${health}`}
            />
            <span
              className={`uppercase tracking-[0.1em] ${STATUS_COLOR[health]}`}
              aria-hidden="true"
            >
              {STATUS[health]}
            </span>
          </span>
          <span className="stat" data-testid="index-version">
            <span className="stat-label">index</span>{' '}
            <span>{indexVersion ?? 'unknown'}</span>
          </span>
          <span className="stat" data-testid="status-requests">
            <span className="stat-label">model req</span>{' '}
            <span className={modelRequests === 1 ? 'text-up' : ''}>
              {modelRequests === null ? '--' : modelRequests}
            </span>
          </span>
          <span className="stat">
            <span className="stat-label">last</span>{' '}
            {lastMeta !== null ? (
              <CostBadge
                key={`${lastMeta.latency_ms.total}:${lastMeta.cost_usd}`}
                latencyMs={lastMeta.latency_ms.total}
                costUsd={lastMeta.cost_usd}
              />
            ) : (
              <span className="text-muted">--</span>
            )}
          </span>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <ThemeToggle />
          {children}
        </div>
      </div>
      {nav}
    </header>
  );
}
