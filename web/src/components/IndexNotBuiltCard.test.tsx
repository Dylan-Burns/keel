import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {IndexNotBuiltCard} from './IndexNotBuiltCard';

describe('IndexNotBuiltCard', () => {
  it('shows the build command and checks again', () => {
    const onRecheck = vi.fn();
    render(<IndexNotBuiltCard onRecheck={onRecheck} />);
    expect(screen.getByText('uv run keel index')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: 'Check again'}));
    expect(onRecheck).toHaveBeenCalledOnce();
  });
});
