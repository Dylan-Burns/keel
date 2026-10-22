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

  it('renders 1 block per markdown block, a script as text while streaming', () => {
    render(
      <AnswerMarkdown
        markdown={
          'First <script>x()</script>\n\n- a\n- b\n\n| h |\n| - |\n| c |'
        }
        streaming
      />,
    );
    const root = screen.getByTestId('answer-markdown');
    expect(screen.getAllByTestId('answer-block')).toHaveLength(3);
    expect(root.querySelector('script')).toBeNull();
    expect(root).toHaveTextContent('First <script>x()</script>');
    expect(root.querySelector('table')).not.toBeNull();
    expect(screen.getByTestId('answer-cursor')).toBeInTheDocument();
  });

  it('a streamed section does not re-mount on later deltas', () => {
    const deltas = [
      'Apple grew ',
      'revenue.\n\nTesla ',
      'cut prices',
      ' in **2025**.\n\n- risk one',
      '\n- risk two',
    ];
    const {rerender} = render(
      <AnswerMarkdown markdown={deltas[0] ?? ''} streaming />,
    );
    const seen: Element[][] = [];
    let text = '';
    for (const delta of deltas) {
      text += delta;
      rerender(<AnswerMarkdown markdown={text} streaming />);
      seen.push(screen.getAllByTestId('answer-block'));
    }
    // The final event swaps nothing: the same element, the same blocks.
    rerender(<AnswerMarkdown markdown={text} />);
    const last = screen.getAllByTestId('answer-block');
    expect(last).toHaveLength(3);
    for (const blocks of seen) {
      blocks.forEach((block, index) => {
        expect(last[index], `block ${index}`).toBe(block);
      });
    }
    expect(last[1]?.querySelector('strong')).toHaveTextContent('2025');
    expect(screen.queryByTestId('answer-cursor')).toBeNull();
  });
});
