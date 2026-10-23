import {fireEvent, render, screen} from '@testing-library/react';
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
    const card = screen.getAllByTestId('citation-card')[0];
    expect(card).toHaveTextContent('Part II, Item 1A. Risk Factors');
    expect(card).toHaveTextContent(
      'Passage 3 of 7 \u00b7 Filed 2023-02-03 \u00b7 Accession 0000320193-23-000006',
    );
    const deep = screen.getAllByTestId('sec-link')[0];
    expect(deep?.getAttribute('href')).toContain(
      '#:~:text=The%20Company%20depends%20on%20component%20suppliers',
    );
    expect(deep).toHaveTextContent('(jumps to the excerpt)');
    // A citation without a location keeps the section title line.
    expect(screen.getAllByTestId('citation-card')[1]).toHaveTextContent(
      'Risk Factors, FY2025',
    );
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

  it('opens the filing reader from a citation card', () => {
    const onOpenReader = vi.fn();
    render(
      <RightPanel
        run={runOf(RESPONSE_1)}
        selected={null}
        open
        onClose={vi.fn()}
        onOpenReader={onOpenReader}
      />,
    );
    const buttons = screen.getAllByTestId('view-in-filing');
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[0]!);
    expect(onOpenReader).toHaveBeenCalledWith(
      RESPONSE_1.citations_resolved[0]?.chunk_id,
    );
  });
});
