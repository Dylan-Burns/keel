import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {EXAMPLES} from '../lib/examples';
import {ExampleChips} from './ExampleChips';

describe('ExampleChips', () => {
  it('renders the 3 examples and picks one', () => {
    const onPick = vi.fn();
    render(
      <ExampleChips examples={EXAMPLES} disabled={false} onPick={onPick} />,
    );
    const chips = screen.getAllByTestId('example-chip');
    expect(chips).toHaveLength(3);
    fireEvent.click(chips[1] as HTMLElement);
    expect(onPick).toHaveBeenCalledWith(EXAMPLES[1]);
  });

  it('turns off with the Ask button', () => {
    render(<ExampleChips examples={EXAMPLES} disabled onPick={vi.fn()} />);
    for (const chip of screen.getAllByTestId('example-chip')) {
      expect(chip).toBeDisabled();
    }
  });
});
