import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {RESPONSE_1} from '../testing/fixtures';
import {TopBar} from './TopBar';

describe('TopBar', () => {
  it('shows the name, the index version, and the health dot', () => {
    render(<TopBar indexVersion="1.0.0" health="green" lastMeta={null} />);
    expect(
      screen.getByRole('heading', {level: 1, name: 'Keel'}),
    ).toBeInTheDocument();
    expect(screen.getByTestId('index-version')).toHaveTextContent(
      'index 1.0.0',
    );
    expect(
      screen.getByRole('img', {name: 'Service health: green'}),
    ).toHaveAttribute('data-health', 'green');
    expect(screen.queryByTestId('cost-badge')).toBeNull();
  });

  it('shows the cost badge of the last answer', () => {
    render(
      <TopBar indexVersion={null} health="amber" lastMeta={RESPONSE_1.meta} />,
    );
    expect(screen.getByTestId('cost-badge')).toHaveAttribute(
      'data-final',
      '1.8 s, $0.012',
    );
    expect(screen.getByTestId('index-version')).toHaveTextContent(
      'index unknown',
    );
  });
});
