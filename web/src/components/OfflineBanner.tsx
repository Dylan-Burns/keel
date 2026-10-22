import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import {banner, pick} from '../motion/presets';

/**
 * The red offline banner from the browser `offline` event. The last answer
 * stays on screen (table 14.6).
 *
 * @return The banner.
 */
export function OfflineBanner(): JSX.Element {
  const reduced = useReducedMotion();
  return (
    <motion.div
      variants={pick(banner.slide, reduced)}
      initial="hidden"
      animate="visible"
      role="alert"
      className="notice notice-down rounded-none border-x-0 border-t-0 text-[13px]"
      data-testid="banner-offline"
    >
      <strong className="font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-down">
        Offline.
      </strong>{' '}
      The browser cannot reach the service. The last answer stays on screen.
    </motion.div>
  );
}
