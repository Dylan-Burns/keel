import {describe, expect, it} from 'vitest';

import type {ChunkLocation} from '../api/types';
import {
  citationLink,
  deepLink,
  describeLocation,
  positionLabel,
  textFragment,
} from './fragment';

const URL_10K =
  'https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm';

/** The vectors that tests/unit/test_locations.py checks with the same rule. */
const FRAGMENTS: readonly (readonly [string, string | null])[] = [
  [
    "sales outside the U.S. representing a majority of the Company's total net sales",
    ':~:text=representing%20a%20majority%20of%20the,total%20net%20sales',
  ],
  [
    'We face strong competition for our products and services from a growing list of established and new competitors.',
    ':~:text=We%20face%20strong%20competition%20for%20our,established%20and%20new%20competitors',
  ],
  [
    'subject to complex and changing laws',
    ':~:text=subject%20to%20complex%20and%20changing%20laws',
  ],
  ['Total net sales | 416,161 | 391,035', ':~:text=Total%20net%20sales'],
  [
    'TABLE: **Products** | $ 307,003 | Services and other | 109,158',
    ':~:text=Services%20and%20other',
  ],
  ['$ 416,161 | 391,035', null],
  ['A-1 “B”', null],
];

const LOCATION: ChunkLocation = {
  section_label: 'Part II, Item 8. Financial Statements',
  heading: 'Financial Statements and Supplementary Data',
  item_label: 'Item 8',
  anchor: 'Revenue by Reportable Segments',
  passage: 12,
  passages: 84,
  is_table: true,
  filing_date: '2025-10-31',
  accession: '0000320193-25-000079',
};

describe('textFragment', () => {
  it.each(FRAGMENTS)('follows the shared rule for %s', (quote, expected) => {
    expect(textFragment(quote)).toBe(expected);
  });

  it('percent-encodes every symbol, including - , and &', () => {
    expect(textFragment('x', 'Item 7A. R&D, a-b')).toBe(':~:text=Item%207A');
    expect(textFragment('', 'R&D costs, net-of-tax')).toBe(':~:text=costs');
    for (const [quote] of FRAGMENTS) {
      const body = (textFragment(quote) ?? '').replace(':~:text=', '');
      expect(body).toMatch(/^[A-Za-z0-9%,]*$/);
    }
  });

  it('starts a table quote at its anchor, the table title', () => {
    const title = 'Third Quarter of Fiscal Year 2026 Summary';
    expect(textFragment('Revenue | $ 57,006 | 22 | %', title)).toBe(
      ':~:text=Third%20Quarter%20of%20Fiscal%20Year%202026%20Summary',
    );
    expect(textFragment('Total net sales | 1', 'Net Sales')).toBe(
      ':~:text=Net%20Sales',
    );
    expect(textFragment('$ 1 | 2')).toBeNull();
    expect(textFragment('$ 1', 'Segment Results')).toBe(
      ':~:text=Segment%20Results',
    );
  });
});

describe('deepLink', () => {
  it('adds the fragment to an SEC URL and replaces an old one', () => {
    const quote =
      'The Company has a minority market share in the global market';
    const deep = `${URL_10K}#:~:text=The%20Company%20has%20a%20minority%20market,in%20the%20global%20market`;
    expect(deepLink(URL_10K, quote)).toBe(deep);
    expect(deepLink(`${URL_10K}#old`, quote)).toBe(deep);
  });

  it('keeps the plain URL when no fragment can be built', () => {
    expect(deepLink(URL_10K, '$ 1')).toBe(URL_10K);
    expect(deepLink(null, 'words words words')).toBeNull();
    expect(deepLink('https://evil.example/x', 'a b c d')).toBe(
      'https://evil.example/x',
    );
  });

  it('anchors a table passage on its title', () => {
    expect(citationLink(URL_10K, '$ 1 | 2', LOCATION)).toBe(
      `${URL_10K}#:~:text=Revenue%20by%20Reportable%20Segments`,
    );
    expect(
      citationLink(URL_10K, '$ 1 | 2', {...LOCATION, is_table: false}),
    ).toBe(URL_10K);
  });
});

describe('location labels', () => {
  it('names the position and the accession', () => {
    expect(positionLabel(LOCATION)).toBe('Table, passage 12 of 84');
    expect(positionLabel({...LOCATION, is_table: false})).toBe(
      'Passage 12 of 84',
    );
    expect(positionLabel({...LOCATION, is_table: false, passages: 0})).toBe('');
    expect(describeLocation(LOCATION)).toBe(
      'Part II, Item 8. Financial Statements, table, passage 12 of 84, accession 0000320193-25-000079',
    );
    expect(describeLocation(null)).toBe('');
  });
});
