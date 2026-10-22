import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {SharedNotice} from './SharedNotice';

describe('SharedNotice', () => {
  it('renders nothing outside the shared route', () => {
    const {container} = render(<SharedNotice load="none" requestId="r-1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('marks a shared answer read only', () => {
    render(<SharedNotice load="loaded" requestId="r-1" />);
    const notice = screen.getByTestId('shared-notice');
    expect(notice).toHaveTextContent('A shared answer, read only.');
    expect(notice).toHaveTextContent('r-1');
    expect(notice).toHaveAttribute('role', 'status');
  });

  it('says when no store holds the answer', () => {
    render(<SharedNotice load="missing" requestId="gone" />);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'This answer is no longer stored.',
    );
  });
});
