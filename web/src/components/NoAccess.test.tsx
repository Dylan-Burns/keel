import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {NoAccess} from './NoAccess';

describe('NoAccess', () => {
  it('shows the message and saves a trimmed token', () => {
    const onSave = vi.fn();
    render(
      <NoAccess
        message="Enter your access token to read the comp sets."
        onSave={onSave}
      />,
    );
    expect(
      screen.getByRole('heading', {name: 'Access token required'}),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Enter your access token to read the comp sets.'),
    ).toBeInTheDocument();
    const field = screen.getByLabelText('Access token');
    fireEvent.click(screen.getByRole('button', {name: 'Continue'}));
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.change(field, {target: {value: '  abc  '}});
    fireEvent.click(screen.getByRole('button', {name: 'Continue'}));
    expect(onSave).toHaveBeenCalledWith('abc');
    expect(field).toHaveValue('');
  });

  it('announces a rejected token', () => {
    render(
      <NoAccess
        message="The token was rejected. Enter it again."
        rejected
        onSave={vi.fn()}
      />,
    );
    expect(
      screen.getByRole('heading', {name: 'Access token rejected'}),
    ).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'The token was rejected. Enter it again.',
    );
  });
});
