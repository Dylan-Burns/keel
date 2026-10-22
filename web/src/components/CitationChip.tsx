import type {JSX} from 'react';

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
  if (!valid) {
    return (
      <span
        className="rounded border border-amber-400 bg-amber-50 px-1.5 py-0.5 text-xs text-amber-800"
        data-testid="citation-unverified"
      >
        unverified
      </span>
    );
  }
  return (
    <button
      type="button"
      className="rounded border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-xs text-accent hover:bg-accent/20 disabled:opacity-60"
      data-testid="citation-chip"
      data-chunk-id={chunkId}
      disabled={!clickable}
      onClick={() => onSelect(chunkId)}
    >
      {label}
    </button>
  );
}
