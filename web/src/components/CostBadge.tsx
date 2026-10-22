import {
  animate,
  motion,
  useMotionValue,
  useReducedMotion,
  useTransform,
} from 'motion/react';
import type {JSX} from 'react';
import {useEffect} from 'react';

import {countUp, pickTransition} from '../motion/presets';

/** Props of CostBadge. */
export interface CostBadgeProps {
  /** The measured total latency in milliseconds. */
  readonly latencyMs: number;
  /** The measured cost in US dollars. */
  readonly costUsd: number;
}

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
 * The latency and cost badge of the last answer. It counts up from 0 to the
 * measured values over 600 ms, never to an estimate; with reduced motion it
 * shows the values at once.
 *
 * @param props The props.
 * @return The badge.
 */
export function CostBadge({latencyMs, costUsd}: CostBadgeProps): JSX.Element {
  const reduced = useReducedMotion();
  const progress = useMotionValue(reduced === true ? 1 : 0);
  const text = useTransform(progress, p =>
    p >= 1
      ? badgeText(latencyMs, costUsd)
      : badgeText(latencyMs * p, costUsd * p),
  );
  useEffect(() => {
    if (reduced === true) {
      progress.jump(1);
      return;
    }
    progress.jump(0);
    const controls = animate(progress, 1, pickTransition(countUp, reduced));
    return () => controls.stop();
  }, [progress, reduced, latencyMs, costUsd]);
  return (
    <motion.span
      className="rounded bg-slate-100 px-2 py-0.5 text-xs tabular-nums text-slate-700"
      data-testid="cost-badge"
      data-final={badgeText(latencyMs, costUsd)}
    >
      {text}
    </motion.span>
  );
}
