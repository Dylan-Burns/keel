import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {AnswerMarkdown} from './AnswerMarkdown';

describe('AnswerMarkdown', () => {
  it('renders markdown and shows a script as text', () => {
    render(
      <AnswerMarkdown markdown={'**Bold** <script>window.x = 1</script>'} />,
    );
    const root = screen.getByTestId('answer-markdown');
    expect(root.querySelector('strong')).toHaveTextContent('Bold');
    expect(root.querySelector('script')).toBeNull();
    expect(root).toHaveTextContent('<script>window.x = 1</script>');
  });
});
