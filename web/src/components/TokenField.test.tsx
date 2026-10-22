import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {TokenField} from './TokenField';

describe('TokenField', () => {
  it('saves a trimmed token', () => {
    const onSave = vi.fn();
    render(<TokenField hasToken={false} rejected={false} onSave={onSave} />);
    fireEvent.change(screen.getByLabelText('Access token'), {
      target: {value: ' t0k '},
    });
    fireEvent.click(screen.getByRole('button', {name: 'Save'}));
    expect(onSave).toHaveBeenCalledWith('t0k');
  });

  it('collapses to a change button with a token, and asks again after a 401', () => {
    const {rerender} = render(
      <TokenField hasToken rejected={false} onSave={vi.fn()} />,
    );
    expect(
      screen.getByRole('button', {name: 'Change token'}),
    ).toBeInTheDocument();
    rerender(<TokenField hasToken rejected onSave={vi.fn()} />);
    expect(
      screen.getByLabelText('Token rejected, enter it again'),
    ).toBeInTheDocument();
  });
});
