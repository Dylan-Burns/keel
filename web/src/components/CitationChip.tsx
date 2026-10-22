import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import {complete, pick} from '../motion/presets';

/** Props of CitationChip. */
export interface CitationChipProps {
  readonly chunkId: string;
  /** The short label, such as `AAPL FY2025`. */
  readonly label: string;
  /** False for a citation the validator removed or could not resolve. */
  readonly valid: boolean;
  /** False until the `final` event: the chips become clickable then. */
  readonly clickable: boolean;
  readonly onSelect: (chunkId: string) => void;
}

/**
 * 1 citation chip. A chip that failed validation renders `unverified`
 * as text, never as a button.
 *
 * @param props The props.
 * @return The chip.
 */
export function CitationChip({
  chunkId,
  label,
  valid,
  clickable,
  onSelect,
}: CitationChipProps): JSX.Element {
  const reduced = useReducedMotion();
  if (!valid) {
    return (
      <span className="tag tag-warn" data-testid="citation-unverified">
        unverified
      </span>
    );
  }
  return (
    <motion.button
      type="button"
      variants={pick(complete.chip, reduced)}
      className="tag tag-accent cursor-pointer disabled:cursor-default"
      data-testid="citation-chip"
      data-chunk-id={chunkId}
      disabled={!clickable}
      onClick={() => onSelect(chunkId)}
    >
      {label}
    </motion.button>
  );
}
