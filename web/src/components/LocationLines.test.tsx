import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import type {ChunkLocation} from '../api/types';
import {LocationLines} from './LocationLines';

const LOCATION: ChunkLocation = {
  section_label: 'Part I, Item 1A. Risk Factors',
  heading: 'Risk Factors',
  item_label: 'Item 1A',
  passage: 3,
  passages: 36,
  is_table: false,
  filing_date: '2025-10-31',
  accession: '0000320193-25-000079',
};

describe('LocationLines', () => {
  it('shows the part, item, passage, filing date, and accession', () => {
    render(<LocationLines location={LOCATION} fallback="Risk Factors" />);
    expect(screen.getByTestId('citation-section')).toHaveTextContent(
      'Part I, Item 1A. Risk Factors',
    );
    expect(screen.getByTestId('citation-position')).toHaveTextContent(
      'Passage 3 of 36 · Filed 2025-10-31 · Accession 0000320193-25-000079',
    );
  });

  it('marks a table and an unverified citation', () => {
    render(
      <LocationLines
        location={{...LOCATION, is_table: true, accession: null}}
        fallback=""
        unverified
      />,
    );
    expect(screen.getByTestId('citation-section')).toHaveTextContent(
      'Risk Factors, unverified',
    );
    expect(screen.getByTestId('citation-position')).toHaveTextContent(
      'Table, passage 3 of 36 · Filed 2025-10-31',
    );
  });

  it('falls back to the section title without a location', () => {
    render(<LocationLines location={null} fallback="Risk Factors, FY2025" />);
    expect(screen.getByTestId('citation-section')).toHaveTextContent(
      'Risk Factors, FY2025',
    );
    expect(screen.queryByTestId('citation-position')).toBeNull();
  });
});
