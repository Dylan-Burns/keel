import {describe, expect, it} from 'vitest';

import {parseTable, splitQuote} from './reader';

describe('parseTable', () => {
  it('splits the caption, units, columns, and rows', () => {
    const table = parseTable(
      'TABLE: Net Sales | units: $ in millions | columns: 2025 | 2024\nProducts | $ 1 | $ 2\n($ in millions)',
    );
    expect(table).toEqual({
      caption: 'Net Sales',
      units: '$ in millions',
      columns: ['2025', '2024'],
      rows: [['Products', '$ 1', '$ 2'], ['($ in millions)']],
    });
  });

  it('handles a table with no title and rejects prose', () => {
    expect(parseTable('TABLE: | columns: A\nx | 1')?.caption).toBe('');
    expect(parseTable('Revenue grew.')).toBeNull();
  });
});

describe('splitQuote', () => {
  it('finds a verbatim quote', () => {
    expect(splitQuote('a b c d', 'b c')).toEqual({
      before: 'a ',
      match: 'b c',
      after: ' d',
    });
  });

  it('matches across wrapped whitespace and escapes symbols', () => {
    expect(
      splitQuote('cost (net)\nof $5.0 billion', 'cost (net) of $5.0'),
    ).toEqual({before: '', match: 'cost (net)\nof $5.0', after: ' billion'});
  });

  it('returns null for a missing or empty quote', () => {
    expect(splitQuote('a b', 'z')).toBeNull();
    expect(splitQuote('a b', '  ')).toBeNull();
  });
});
