/** Citation lookups shared by the answer area and the right panel. */
import type {Citation, ResolvedCitation, RetrievedChunk} from '../api/types';
import type {Run} from '../state';

/** What a citation chip needs to render. */
export interface ChipInfo {
  readonly chunkId: string;
  readonly label: string;
  readonly valid: boolean;
}

/**
 * The retrieved chunk of an ID, if the context holds it.
 *
 * @param run The run.
 * @param chunkId The chunk ID.
 * @return The chunk or undefined.
 */
export function findChunk(
  run: Run,
  chunkId: string,
): RetrievedChunk | undefined {
  return run.retrieval?.chunks.find(c => c.chunk_id === chunkId);
}

/**
 * The resolved citation of an ID, after the `final` event.
 *
 * @param run The run.
 * @param chunkId The chunk ID.
 * @return The resolved citation or undefined.
 */
export function findResolved(
  run: Run,
  chunkId: string,
): ResolvedCitation | undefined {
  return run.final?.citations_resolved.find(c => c.chunk_id === chunkId);
}

/**
 * The model citation (claim and quote) of an ID.
 *
 * @param run The run.
 * @param chunkId The chunk ID.
 * @return The citation or undefined.
 */
export function findCitation(run: Run, chunkId: string): Citation | undefined {
  return run.final?.answer.citations.find(c => c.chunk_id === chunkId);
}

/**
 * The chip of a citation. Before `final`, a chip is valid when the context
 * holds its chunk; after, the validator decides.
 *
 * @param run The run.
 * @param chunkId The cited chunk ID.
 * @return The chip info.
 */
export function chipFor(run: Run, chunkId: string): ChipInfo {
  const chunk = findChunk(run, chunkId);
  const resolved = findResolved(run, chunkId);
  const label =
    resolved !== undefined
      ? resolved.fiscal_label
      : chunk !== undefined
        ? `${chunk.ticker} ${chunk.fiscal_label}`
        : chunkId;
  const ticker = chunk?.ticker ?? '';
  const valid =
    run.final === null ? chunk !== undefined : resolved?.valid === true;
  return {
    chunkId,
    label:
      resolved !== undefined && ticker !== '' ? `${ticker} ${label}` : label,
    valid,
  };
}
