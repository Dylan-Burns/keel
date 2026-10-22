import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import {banner, pick} from '../motion/presets';

/** Props of ProviderDownBanner. */
export interface ProviderDownBannerProps {
  readonly message: string;
  /** Null when there is no question to retry. */
  readonly onRetry: (() => void) | null;
  readonly retryEnabled: boolean;
}

/**
 * The red provider-down banner: the model is unavailable, the retrieved
 * chunks stay in the right panel, and a Retry button (table 14.6).
 *
 * @param props The props.
 * @return The banner.
 */
export function ProviderDownBanner({
  message,
  onRetry,
  retryEnabled,
}: ProviderDownBannerProps): JSX.Element {
  const reduced = useReducedMotion();
  return (
    <motion.div
      variants={pick(banner.slide, reduced)}
      initial="hidden"
      animate="visible"
      role="alert"
      className="notice notice-down flex flex-wrap items-center gap-3 text-[13px]"
      data-testid="banner-provider-down"
    >
      <span>
        <strong className="font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-down">
          Model unavailable.
        </strong>{' '}
        {message}
      </span>
      {onRetry !== null && (
        <button
          type="button"
          className="btn btn-danger ml-auto"
          disabled={!retryEnabled}
          onClick={onRetry}
        >
          Retry
        </button>
      )}
    </motion.div>
  );
}
