import {render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {RESPONSE_1} from '../testing/fixtures';
import {runOf} from '../testing/runs';
import {RightPanel} from './RightPanel';

describe('RightPanel', () => {
  it('lists the retrieved chunks with scores and the collapse count while loading', () => {
    render(
      <RightPanel
        run={runOf(RESPONSE_1, 3)}
        selected={null}
        open={false}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getAllByTestId('chunk-row')).toHaveLength(2);
    expect(screen.getByTestId('collapse-count')).toHaveTextContent(
      '2 near-duplicates collapsed',
    );
    expect(screen.queryByTestId('citation-list')).toBeNull();
  });

  it('shows the citations with SEC links and quotes after final', () => {
    render(
      <RightPanel
        run={runOf(RESPONSE_1)}
        selected={null}
        open
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByTestId('citation-list')).toHaveTextContent(
      'The Company depends on component suppliers',
    );
    for (const link of screen.getAllByTestId('sec-link')) {
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
      expect(link).toHaveAttribute('target', '_blank');
    }
  });

  it('shows the opened chunk text as text', () => {
    const run = runOf(RESPONSE_1);
    const chunk = run.retrieval?.chunks[0];
    if (chunk === undefined) {
      throw new Error('fixture');
    }
    render(
      <RightPanel
        run={run}
        selected={{
          chunkId: chunk.chunk_id,
          detail: {...chunk, section_title: 'Risk Factors', text: '<b>raw</b>'},
          error: null,
        }}
        open
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByTestId('selected-chunk')).toHaveTextContent(
      '<b>raw</b>',
    );
    expect(screen.getByTestId('selected-chunk').querySelector('b')).toBeNull();
  });
});
