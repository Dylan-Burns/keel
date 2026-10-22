import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {RateLimitedCard} from './RateLimitedCard';

describe('RateLimitedCard', () => {
  it('shows the countdown', () => {
    render(<RateLimitedCard secondsLeft={12} />);
    expect(screen.getByTestId('countdown')).toHaveTextContent('12');
  });
});
