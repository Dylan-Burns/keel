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
        : fallbackChip(chunkId).label;
  const ticker = chunk?.ticker ?? resolved?.ticker ?? '';
  const valid =
    run.final === null ? chunk !== undefined : resolved?.valid === true;
  return {
    chunkId,
    label:
      resolved !== undefined && ticker !== '' ? `${ticker} ${label}` : label,
    valid,
  };
}

/** A chunk ID (chapter 7.11), the same pattern as `keel/citations.py`. */
const CHUNK_ID =
  /^([A-Z0-9][A-Z0-9.-]*)_(10[KQ])_(\d{4})-\d{2}-\d{2}__([a-z_]+)__\d{4,}$/;

/** A fact ID such as `facts:NVDA:Revenues:Q1FY2026`. */
const FACT_ID =
  /^facts:([A-Z0-9][A-Z0-9.-]*):([A-Za-z][A-Za-z0-9_]*):((?:Q[1-4])?FY\d{4})$/;

/** The section titles of `keel/citations.py`, for the chip names. */
const SECTION_TITLES: Readonly<Record<string, string>> = {
  business: 'Business',
  risk_factors: 'Risk Factors',
  legal_proceedings: 'Legal Proceedings',
  mdna: "Management's Discussion and Analysis",
  market_risk: 'Quantitative and Qualitative Disclosures About Market Risk',
  financial_statements: 'Financial Statements',
  controls: 'Controls and Procedures',
  other: 'Other',
  unknown: 'Unclassified section',
};

/** The section title of the XBRL company facts. */
const FACTS_SECTION = 'XBRL company facts';

/** What an inline citation chip in the answer text needs to render. */
export interface InlineChip extends ChipInfo {
  /** The full source, such as `Apple Inc. 10-K FY2025, Risk Factors`. */
  readonly source: string;
  /** True for an XBRL fact rather than a filing chunk. */
  readonly fact: boolean;
}

/**
 * True for a text that is a whole chunk ID or fact ID.
 *
 * @param text The text.
 * @return Whether the text is a citation ID.
 */
export function isCitationId(text: string): boolean {
  return CHUNK_ID.test(text) || FACT_ID.test(text);
}

/**
 * The chip of an ID read from the ID alone: ticker, form, and period year
 * for a chunk, ticker and fiscal label for a fact. Never the raw ID.
 *
 * @param chunkId The cited chunk ID or fact ID.
 * @return The short label and the full source.
 */
export function fallbackChip(chunkId: string): {
  readonly label: string;
  readonly source: string;
  readonly fact: boolean;
} {
  const fact = FACT_ID.exec(chunkId);
  if (fact !== null) {
    const [, ticker = '', concept = '', period = ''] = fact;
    return {
      label: `${ticker} facts ${period}`,
      source: `${ticker} ${FACTS_SECTION}, ${concept} ${period}`,
      fact: true,
    };
  }
  const chunk = CHUNK_ID.exec(chunkId);
  if (chunk !== null) {
    const [, ticker = '', form = '', year = '', section = ''] = chunk;
    const dashed = `${form.slice(0, 2)}-${form.slice(2)}`;
    const title = SECTION_TITLES[section] ?? section.replace(/_/g, ' ');
    return {
      label: `${ticker} ${dashed} ${year}`,
      source: `${ticker} ${dashed} period ending ${year}, ${title}`,
      fact: false,
    };
  }
  const head = chunkId.split(/[_:]/).find(part => part !== '') ?? 'source';
  return {label: head, source: chunkId, fact: false};
}

/**
 * The inline chip of an ID cited in the answer text: the same short label
 * as the finding chips (`AAPL FY2025`, `NVDA facts FY2025`), and the full
 * source for the accessible name. The run's citations and retrieval decide
 * the label; the ID alone is the fallback.
 *
 * @param run The run.
 * @param chunkId The cited chunk ID or fact ID.
 * @return The inline chip info.
 */
export function inlineChipFor(run: Run, chunkId: string): InlineChip {
  const chunk = findChunk(run, chunkId);
  const resolved = findResolved(run, chunkId);
  const fallback = fallbackChip(chunkId);
  const valid =
    run.final === null ? chunk !== undefined : resolved?.valid === true;
  const ticker = chunk?.ticker ?? resolved?.ticker ?? '';
  const period = resolved?.fiscal_label ?? chunk?.fiscal_label ?? '';
  let label = fallback.label;
  if (ticker !== '' && period !== '') {
    label = fallback.fact ? `${ticker} facts ${period}` : `${ticker} ${period}`;
  }
  let source = fallback.source;
  if (resolved !== undefined) {
    source = `${resolved.filing_name}, ${resolved.section_title}`;
  } else if (chunk !== undefined) {
    const title = SECTION_TITLES[chunk.section] ?? chunk.section;
    source = `${chunk.filing_name}, ${title}`;
  }
  return {chunkId, label, source, valid, fact: fallback.fact};
}
