import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {PartialCoverageBanner} from './PartialCoverageBanner';

describe('PartialCoverageBanner', () => {
  it('names the absent companies and counts the unverified findings', () => {
    render(
      <PartialCoverageBanner
        companiesMissing={['TSLA']}
        unverifiedFindings={2}
      />,
    );
    const banner = screen.getByTestId('banner-partial-coverage');
    expect(banner).toHaveTextContent('No filings in the corpus for TSLA.');
    expect(banner).toHaveTextContent('2 findings have no valid citation');
  });
});
