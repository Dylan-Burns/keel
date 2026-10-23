import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {ReaderButton} from './ReaderButton';

describe('ReaderButton', () => {
  it('opens the reader on a chunk', () => {
    const onOpen = vi.fn();
    render(
      <ReaderButton
        chunkId="AAPL_10K_2025-09-27__risk_factors__0002"
        onOpen={onOpen}
      />,
    );
    fireEvent.click(screen.getByTestId('view-in-filing'));
    expect(onOpen).toHaveBeenCalledWith(
      'AAPL_10K_2025-09-27__risk_factors__0002',
    );
  });

  it('shows nothing for a fact or without a handler', () => {
    const {container} = render(
      <ReaderButton chunkId="facts:NVDA:Revenues:FY2025" onOpen={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
    const other = render(
      <ReaderButton
        chunkId="AAPL_10K_2025-09-27__risk_factors__0002"
        onOpen={undefined}
      />,
    );
    expect(other.container).toBeEmptyDOMElement();
  });
});
