import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {isCitedRow} from '../lib/reader';
import {ReaderTable} from './ReaderTable';

const TABLE = {
  caption: 'Third Quarter Summary',
  units: '$ in millions',
  columns: ['Oct 26, 2025', 'Jul 27, 2025'],
  rows: [
    ['Revenue', '$ 57,006', '$ 46,743'],
    ['Gross margin', '73.4 %', '72.4 %'],
  ],
};

describe('ReaderTable', () => {
  it('renders a table with the cited row marked', () => {
    render(
      <ReaderTable table={TABLE} quote="Revenue | $ 57,006 | $ 46,743 | 22" />,
    );
    const table = screen.getByTestId('reader-table');
    expect(table.querySelector('caption')).toHaveTextContent(
      'Third Quarter Summary ($ in millions)',
    );
    // The header gets a blank cell over the row labels.
    expect(table.querySelectorAll('th')).toHaveLength(3);
    const marks = screen.getAllByTestId('reader-mark');
    expect(marks.map(m => m.textContent)).toEqual([
      'Revenue',
      '$ 57,006',
      '$ 46,743',
    ]);
  });

  it('marks nothing without a quote', () => {
    render(<ReaderTable table={TABLE} />);
    expect(screen.queryByTestId('reader-mark')).toBeNull();
    expect(isCitedRow(['a'], undefined)).toBe(false);
    expect(isCitedRow([''], 'x')).toBe(false);
  });
});
