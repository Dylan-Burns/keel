import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {RESPONSE_1, RESPONSE_2} from '../testing/fixtures';
import {runOf} from '../testing/runs';
import {AnswerArea} from './AnswerArea';

describe('AnswerArea', () => {
  it('loading: shows the progress steps and no answer yet', () => {
    render(
      <AnswerArea
        run={runOf(RESPONSE_2, 2)}
        streaming={false}
        askEnabled={false}
        onSelectCitation={vi.fn()}
        onAsk={vi.fn()}
      />,
    );
    expect(screen.getByTestId('progress-steps')).toHaveAttribute(
      'data-order',
      'understanding,retrieval',
    );
    expect(screen.queryByTestId('answer-markdown')).toBeNull();
  });

  it('streaming: renders the deltas as answer blocks with the cursor', () => {
    render(
      <AnswerArea
        run={runOf(RESPONSE_2, 5)}
        streaming
        askEnabled={false}
        onSelectCitation={vi.fn()}
        onAsk={vi.fn()}
      />,
    );
    const answer = screen.getByTestId('answer-markdown');
    expect(answer).toHaveAttribute('data-streaming', 'true');
    expect(Number(answer.getAttribute('data-blocks'))).toBeGreaterThan(0);
    expect(answer.textContent).not.toBe('');
    expect(screen.getByTestId('answer-cursor')).toBeInTheDocument();
  });

  it('the final event keeps the streamed answer element and its blocks', () => {
    const props = {
      askEnabled: false,
      onSelectCitation: vi.fn(),
      onAsk: vi.fn(),
    };
    const {rerender} = render(
      <AnswerArea run={runOf(RESPONSE_2, 6)} streaming {...props} />,
    );
    const answer = screen.getByTestId('answer-markdown');
    const first = screen.getAllByTestId('answer-block')[0];
    rerender(
      <AnswerArea run={runOf(RESPONSE_2)} streaming={false} {...props} />,
    );
    expect(screen.getByTestId('answer-markdown')).toBe(answer);
    expect(screen.getAllByTestId('answer-block')[0]).toBe(first);
    expect(answer).toHaveAttribute('data-streaming', 'false');
  });

  it('complete: shows the answer, confidence, coverage, findings, table, gaps, next questions', () => {
    const onAsk = vi.fn();
    render(
      <AnswerArea
        run={runOf(RESPONSE_1)}
        streaming={false}
        askEnabled
        onSelectCitation={vi.fn()}
        onAsk={onAsk}
      />,
    );
    expect(
      screen.getByTestId('answer-markdown').querySelector('strong'),
    ).toHaveTextContent('foreign exchange');
    expect(screen.getByTestId('confidence-chip')).toHaveTextContent(
      'confidence medium',
    );
    expect(screen.getByTestId('coverage-indicator')).toHaveTextContent(
      'TSLA: no filings',
    );
    expect(screen.getAllByTestId('findings-group')).toHaveLength(2);
    expect(screen.getByTestId('comparison-table')).toBeInTheDocument();
    expect(screen.getByTestId('gaps')).toHaveTextContent('No Tesla filing');
    fireEvent.click(
      screen.getByRole('button', {name: /credit risk in FY2025/}),
    );
    expect(onAsk).toHaveBeenCalledWith(RESPONSE_1.answer.next_questions[0]);
  });
});
