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
      className="flex flex-wrap items-center gap-3 rounded-lg border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-900"
      data-testid="banner-provider-down"
    >
      <span>
        <strong className="font-medium">Model unavailable.</strong> {message}
      </span>
      {onRetry !== null && (
        <button
          type="button"
          className="ml-auto rounded bg-red-700 px-3 py-1 text-white disabled:opacity-50"
          disabled={!retryEnabled}
          onClick={onRetry}
        >
          Retry
        </button>
      )}
    </motion.div>
  );
}
