import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import {banner, pick} from '../motion/presets';

/** Props of PartialCoverageBanner. */
export interface PartialCoverageBannerProps {
  readonly companiesMissing: readonly string[];
  readonly unverifiedFindings: number;
}

/**
 * The yellow partial-coverage banner: it names the absent companies or the
 * count of unverified findings, above the answer (table 14.6).
 *
 * @param props The props.
 * @return The banner.
 */
export function PartialCoverageBanner({
  companiesMissing,
  unverifiedFindings,
}: PartialCoverageBannerProps): JSX.Element {
  const parts: string[] = [];
  if (companiesMissing.length > 0) {
    parts.push(`No filings in the corpus for ${companiesMissing.join(', ')}.`);
  }
  if (unverifiedFindings > 0) {
    parts.push(
      `${unverifiedFindings} finding${unverifiedFindings === 1 ? ' has' : 's have'} no valid citation, marked unverified.`,
    );
  }
  const reduced = useReducedMotion();
  return (
    <motion.div
      variants={pick(banner.slide, reduced)}
      initial="hidden"
      animate="visible"
      role="status"
      className="rounded-lg border border-yellow-300 bg-yellow-50 px-4 py-2 text-sm text-yellow-900"
      data-testid="banner-partial-coverage"
    >
      <strong className="font-medium">Partial coverage.</strong>{' '}
      {parts.join(' ')}
    </motion.div>
  );
}
