import {render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {EXAMPLES} from '../lib/examples';
import {COVERAGE} from '../testing/fixtures';
import {OutOfScopeCard} from './OutOfScopeCard';

describe('OutOfScopeCard', () => {
  it('shows the reason, the covered companies, and the examples', () => {
    render(
      <OutOfScopeCard
        reason="No price predictions."
        coverage={COVERAGE}
        examples={EXAMPLES}
        askEnabled
        onPick={vi.fn()}
      />,
    );
    expect(screen.getByTestId('card-out-of-scope')).toHaveTextContent(
      'No price predictions.',
    );
    expect(
      screen.getByText('Covered companies: AAPL, JPM, NVDA'),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId('example-chip')).toHaveLength(3);
  });
});
