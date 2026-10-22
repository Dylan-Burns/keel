import {motion} from 'motion/react';
import type {JSX} from 'react';
import {useState} from 'react';

import type {EvalGate} from '../api/types';
import {evalPage, pick} from '../motion/presets';

/** Where a gate value and its threshold sit on a bar from 0 to 1. */
export interface GateScale {
  /** The filled share of the bar, 0 to 1. */
  readonly fill: number;
  /** The position of the threshold mark, 0 to 1. */
  readonly mark: number;
}

/**
 * Places a gate on its bar: a `>=` gate on a scale from 0 to 1 (or to the
 * larger of the threshold and the value), a `<=` gate on a scale to twice
 * the threshold, so the mark sits in the middle.
 *
 * @param gate The gate.
 * @return The fill and the mark.
 */
export function gateScale(gate: EvalGate): GateScale {
  const value = gate.value ?? 0;
  const top =
    gate.comparator === '>=' || gate.comparator === '>'
      ? Math.max(1, gate.threshold, value)
      : Math.max(2 * gate.threshold, value);
  const share = (x: number): number =>
    top <= 0 ? 0 : Math.min(1, Math.max(0, x / top));
  return {fill: share(value), mark: share(gate.threshold)};
}

/** Props of GateBar. */
export interface GateBarProps {
  readonly gate: EvalGate;
  readonly reduced: boolean | null;
}

/**
 * 1 metric bar of the eval page (W-02). The number is in the DOM before the
 * bar grows; a value that misses its gate turns red when the grow ends.
 *
 * @param props The props.
 * @return The bar.
 */
export function GateBar({gate, reduced}: GateBarProps): JSX.Element {
  const [grown, setGrown] = useState(reduced === true);
  const {fill, mark} = gateScale(gate);
  const failed = gate.passed === false && grown;
  const color = failed
    ? 'bg-down'
    : gate.passed === true
      ? 'bg-up'
      : 'bg-line-strong';
  const state =
    gate.passed === null ? 'pending' : gate.passed ? 'pass' : 'fail';
  return (
    <li
      className="space-y-1.5 px-3 py-2"
      data-testid="eval-gate"
      data-state={state}
      data-red={failed ? 'true' : 'false'}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-[13px]">
        <span>{gate.name}</span>
        <span
          className={`num text-xs ${failed ? 'text-down' : gate.passed === true ? 'text-up' : 'text-ink'}`}
          data-testid="eval-gate-value"
        >
          {gate.value === null ? 'pending' : gate.value_text}
          <span className="text-muted"> (gate {gate.threshold_text})</span>
        </span>
      </div>
      <div className="relative h-1.5 w-full bg-line">
        <div className="h-1.5" style={{width: `${fill * 100}%`}}>
          <motion.div
            className={`h-1.5 origin-left ${color}`}
            variants={pick(evalPage.bar, reduced)}
            onAnimationComplete={() => setGrown(true)}
          />
        </div>
        <span
          className="absolute top-[-3px] h-3 w-px bg-ink"
          style={{left: `${mark * 100}%`}}
          aria-hidden="true"
        />
      </div>
    </li>
  );
}
