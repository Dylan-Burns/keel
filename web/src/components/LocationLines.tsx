import type {JSX} from 'react';

import type {ChunkLocation} from '../api/types';
import {positionLabel} from '../lib/fragment';

/** Props of LocationLines. */
export interface LocationLinesProps {
  /** The place in the filing, or null for a fact or an old answer. */
  readonly location: ChunkLocation | null;
  /** The line shown without a location, such as `Risk Factors, FY2025`. */
  readonly fallback: string;
  /** The filing date when the location does not carry it. */
  readonly filingDate?: string | undefined;
  /** True when the validator marked the citation unverified. */
  readonly unverified?: boolean;
}

/**
 * Where a cited passage sits in its filing: the section label with its part
 * and item number on 1 line, then the position in the item, the filing
 * date, and the accession number. Every string is a JSX text node.
 *
 * @param props The props.
 * @return The lines.
 */
export function LocationLines({
  location,
  fallback,
  filingDate,
  unverified = false,
}: LocationLinesProps): JSX.Element {
  const flag = unverified ? ', unverified' : '';
  if (location === null) {
    return (
      <div
        className="num text-[11px] text-muted"
        data-testid="citation-section"
      >
        {fallback}
        {flag}
      </div>
    );
  }
  const filed = location.filing_date || filingDate || '';
  const details = [
    positionLabel(location),
    filed === '' ? '' : `Filed ${filed}`,
    location.accession === null ? '' : `Accession ${location.accession}`,
  ].filter(part => part !== '');
  return (
    <>
      <div
        className="text-[11.5px] font-medium text-ink-2"
        data-testid="citation-section"
      >
        {location.section_label}
        {flag}
      </div>
      {details.length > 0 && (
        <div
          className="num flex flex-wrap text-[10.5px] text-muted"
          data-testid="citation-position"
        >
          {details.map((part, i) => (
            <span key={part} className="whitespace-nowrap">
              {i > 0 ? '\u00a0\u00b7\u00a0' : ''}
              {part}
            </span>
          ))}
        </div>
      )}
    </>
  );
}
