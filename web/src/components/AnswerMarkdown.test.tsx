import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

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

  const AAPL = 'AAPL_10K_2025-09-27__risk_factors__0000';
  const FACT = 'facts:AAPL:Revenues:FY2025';
  const resolve = (chunkId: string) => ({
    label: chunkId === FACT ? 'AAPL facts FY2025' : 'AAPL FY2025',
    source:
      chunkId === FACT
        ? 'AAPL 10-K filed 2025-10-31, XBRL company facts'
        : 'Apple Inc. 10-K FY2025, Risk Factors',
    valid: true,
  });

  it('shows each cited ID as a chip with the full source as its name', () => {
    const onSelect = vi.fn();
    render(
      <AnswerMarkdown
        markdown={`Apple named supply risk [${AAPL}] and revenue [${FACT}].`}
        resolveCitation={resolve}
        citationsClickable
        onSelectCitation={onSelect}
      />,
    );
    const root = screen.getByTestId('answer-markdown');
    expect(root).not.toHaveTextContent(AAPL);
    expect(root).not.toHaveTextContent('facts:AAPL');
    const chip = screen.getByRole('button', {
      name: 'AAPL FY2025: Apple Inc. 10-K FY2025, Risk Factors',
    });
    expect(chip).toHaveTextContent('AAPL FY2025');
    expect(chip).toBeEnabled();
    expect(
      screen.getByRole('button', {name: /AAPL facts FY2025: .*company facts/}),
    ).toBeInTheDocument();
    fireEvent.click(chip);
    expect(onSelect).toHaveBeenCalledWith(AAPL);
  });

  it('labels a chip from the ID alone without a resolver', () => {
    render(<AnswerMarkdown markdown={`Risk [${AAPL}].`} />);
    expect(screen.getByTestId('inline-citation')).toHaveTextContent(
      'AAPL 10-K 2025',
    );
    expect(screen.getByTestId('answer-markdown')).not.toHaveTextContent(AAPL);
  });

  it('keeps the blocks while chips stream in and turn clickable', () => {
    const parts = [
      'Apple grew [AAPL_10K_2025',
      `-09-27__risk_factors__0000].\n\nTesla [${AAPL}`,
      '] cut prices.',
    ];
    let text = '';
    const {rerender} = render(<AnswerMarkdown markdown="" streaming />);
    const seen: Element[][] = [];
    for (const part of parts) {
      text += part;
      rerender(
        <AnswerMarkdown markdown={text} streaming resolveCitation={resolve} />,
      );
      expect(screen.getByTestId('answer-markdown')).not.toHaveTextContent(
        '[AAPL_',
      );
      seen.push(screen.getAllByTestId('answer-block'));
    }
    expect(screen.getAllByTestId('inline-citation')[0]).toBeDisabled();
    rerender(
      <AnswerMarkdown
        markdown={text}
        resolveCitation={resolve}
        citationsClickable
      />,
    );
    const last = screen.getAllByTestId('answer-block');
    expect(last).toHaveLength(2);
    for (const blocks of seen) {
      blocks.forEach((block, index) => {
        expect(last[index], `block ${index}`).toBe(block);
      });
    }
    expect(screen.getAllByTestId('inline-citation')).toHaveLength(2);
    expect(screen.getAllByTestId('inline-citation')[1]).toBeEnabled();
  });
});
