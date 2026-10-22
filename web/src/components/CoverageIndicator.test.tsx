import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {RESPONSE_1} from '../testing/fixtures';
import {CoverageIndicator} from './CoverageIndicator';

describe('CoverageIndicator', () => {
  it('shows used companies and a gray chip for an absent one', () => {
    render(<CoverageIndicator coverage={RESPONSE_1.answer.coverage} />);
    const chips = screen.getAllByRole('listitem');
    expect(chips[0]).toHaveTextContent('AAPL: 10-Q Q1 FY2023');
    expect(screen.getByText('TSLA: no filings')).toHaveAttribute(
      'data-covered',
      'false',
    );
  });
});
