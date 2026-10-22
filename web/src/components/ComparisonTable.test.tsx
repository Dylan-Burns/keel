import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {ComparisonTable, isNumericCell} from './ComparisonTable';

describe('ComparisonTable', () => {
  it('renders the columns and the cells as text', () => {
    render(
      <ComparisonTable
        table={{columns: ['Company', 'Risk'], rows: [['AAPL', '<b>x</b>']]}}
      />,
    );
    expect(screen.getAllByRole('columnheader').map(h => h.textContent)).toEqual(
      ['Company', 'Risk'],
    );
    expect(screen.getByText('<b>x</b>')).toBeInTheDocument();
    expect(
      screen.getByTestId('comparison-table').querySelector('b'),
    ).toBeNull();
  });

  it('right-aligns a figure and leaves text left', () => {
    for (const cell of ['$94.9B', '(3.2%)', '1,204', '-4.1%', '12 million']) {
      expect(isNumericCell(cell), cell).toBe(true);
    }
    for (const cell of ['Growing list of competitors', 'FY2025', 'AAPL', '']) {
      expect(isNumericCell(cell), cell).toBe(false);
    }
    render(
      <ComparisonTable
        table={{columns: ['Company', 'Revenue'], rows: [['AAPL', '$416B']]}}
      />,
    );
    expect(screen.getByText('$416B')).toHaveClass('cell-num');
    expect(screen.getByText('AAPL')).not.toHaveClass('cell-num');
  });
});
