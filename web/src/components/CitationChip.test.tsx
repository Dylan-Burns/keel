import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {CitationChip} from './CitationChip';

describe('CitationChip', () => {
  it('a valid chip is a button that selects its chunk', () => {
    const onSelect = vi.fn();
    render(
      <CitationChip
        chunkId="c1"
        label="AAPL FY2025"
        valid
        clickable
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByRole('button', {name: 'AAPL FY2025'}));
    expect(onSelect).toHaveBeenCalledWith('c1');
  });

  it('is off until the final event', () => {
    render(
      <CitationChip
        chunkId="c1"
        label="L"
        valid
        clickable={false}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', {name: 'L'})).toBeDisabled();
  });

  it('an invalid chip renders unverified as text', () => {
    render(
      <CitationChip
        chunkId="c1"
        label="L"
        valid={false}
        clickable
        onSelect={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.getByTestId('citation-unverified')).toHaveTextContent(
      'unverified',
    );
  });
});
