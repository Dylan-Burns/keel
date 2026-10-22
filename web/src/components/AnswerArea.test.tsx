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
    expect(screen.queryByTestId('streamed-answer')).toBeNull();
    expect(screen.queryByTestId('answer-markdown')).toBeNull();
  });

  it('streaming: shows the deltas as text with the cursor', () => {
    render(
      <AnswerArea
        run={runOf(RESPONSE_2, 5)}
        streaming
        askEnabled={false}
        onSelectCitation={vi.fn()}
        onAsk={vi.fn()}
      />,
    );
    expect(screen.getByTestId('streamed-answer')).toHaveAttribute(
      'data-deltas',
      '2',
    );
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
