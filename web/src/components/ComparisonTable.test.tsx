import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {ComparisonTable} from './ComparisonTable';

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
});
