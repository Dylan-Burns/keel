import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {StreamedText} from './StreamedText';

describe('StreamedText', () => {
  it('appends the deltas as text nodes, a script included', () => {
    render(
      <StreamedText deltas={['Revenue ', '<script>x()</script>', ' grew']} />,
    );
    const answer = screen.getByTestId('streamed-answer');
    expect(answer).toHaveTextContent('Revenue <script>x()</script> grew');
    expect(answer.querySelector('script')).toBeNull();
    expect(answer).toHaveAttribute('data-deltas', '3');
  });
});
