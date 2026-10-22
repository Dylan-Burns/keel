import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {OfflineBanner} from './OfflineBanner';

describe('OfflineBanner', () => {
  it('is an alert that says the last answer stays', () => {
    render(<OfflineBanner />);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'The last answer stays on screen',
    );
  });
});
