import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {COVERAGE} from '../testing/fixtures';
import {CoverageSummary, coverageLine} from './CoverageSummary';

describe('CoverageSummary', () => {
  it('summarizes companies, filings, and the quarantine', () => {
    render(<CoverageSummary coverage={COVERAGE} hasToken />);
    expect(screen.getByTestId('coverage-summary')).toHaveTextContent(
      '3 companies, 3 filings, 0 quarantined',
    );
    expect(
      coverageLine({
        ...COVERAGE,
        filing_count: 245,
        quarantined: [{ticker: 'GE', file_name: 'f', reason: 'r'}],
      }),
    ).toBe('3 companies, 245 filings, 1 quarantined');
  });

  it('asks for the token before it can load', () => {
    render(<CoverageSummary coverage={null} hasToken={false} />);
    expect(screen.getByTestId('coverage-summary')).toHaveTextContent(
      'Enter the access token',
    );
  });
});
