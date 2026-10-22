import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import type {Example} from '../lib/examples';
import {pageLoad, pick} from '../motion/presets';

/** Props of ExampleChips. */
export interface ExampleChipsProps {
  readonly examples: readonly Example[];
  readonly disabled: boolean;
  readonly onPick: (example: Example) => void;
}

/**
 * The example question chips (question area and out-of-scope card).
 *
 * @param props The props.
 * @return The chips.
 */
export function ExampleChips({
  examples,
  disabled,
  onPick,
}: ExampleChipsProps): JSX.Element {
  const reduced = useReducedMotion();
  return (
    <motion.ul
      className="flex flex-wrap gap-2"
      aria-label="Example questions"
      variants={pick(pageLoad.chips, reduced)}
      initial="hidden"
      animate="visible"
    >
      {examples.map(example => (
        <motion.li key={example.label} variants={pick(pageLoad.chip, reduced)}>
          <button
            type="button"
            className="rounded-full border border-slate-300 bg-white px-3 py-1 text-sm text-slate-700 hover:border-accent hover:text-accent disabled:opacity-50"
            data-testid="example-chip"
            disabled={disabled}
            onClick={() => onPick(example)}
          >
            {example.label}
          </button>
        </motion.li>
      ))}
    </motion.ul>
  );
}
