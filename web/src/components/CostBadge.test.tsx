import {render, screen, waitFor} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {CostBadge, badgeText} from './CostBadge';

describe('CostBadge', () => {
  it('formats latency and cost', () => {
    expect(badgeText(18400, 0.082)).toBe('18.4 s, $0.082');
  });

  it('counts up to the measured value and stops there', async () => {
    render(<CostBadge latencyMs={1840} costUsd={0.012} />);
    const badge = screen.getByTestId('cost-badge');
    expect(badge).toHaveAttribute('data-final', '1.8 s, $0.012');
    await waitFor(() => expect(badge).toHaveTextContent('1.8 s, $0.012'), {
      timeout: 2000,
    });
  });
});
