import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {StaleIndexBanner} from './StaleIndexBanner';

describe('StaleIndexBanner', () => {
  it('names the rebuild command and the warnings', () => {
    render(<StaleIndexBanner warnings={['Checksum differs.']} />);
    const banner = screen.getByTestId('banner-stale-index');
    expect(banner).toHaveTextContent('uv run keel index --incremental');
    expect(banner).toHaveTextContent('Checksum differs.');
  });
});
