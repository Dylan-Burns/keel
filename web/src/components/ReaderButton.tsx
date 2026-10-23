import type {JSX} from 'react';

import {isChunkId} from '../lib/citations';

/** Props of ReaderButton. */
export interface ReaderButtonProps {
  readonly chunkId: string;
  readonly onOpen: ((chunkId: string) => void) | undefined;
}

/**
 * The "View in filing" action of a cited passage: opens the filing reader
 * with the passage highlighted. A fact citation has no filing text to show.
 *
 * @param props The props.
 * @return The button, or nothing.
 */
export function ReaderButton({
  chunkId,
  onOpen,
}: ReaderButtonProps): JSX.Element | null {
  if (onOpen === undefined || !isChunkId(chunkId)) {
    return null;
  }
  return (
    <button
      type="button"
      className="link text-[11px] font-semibold"
      data-testid="view-in-filing"
      onClick={() => onOpen(chunkId)}
    >
      View in filing
    </button>
  );
}
