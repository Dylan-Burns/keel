import {fireEvent, render, screen, within} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import type {EvalGate} from '../../api/types';
import {parseReport} from '../../lib/evalReport';
import {SAMPLE_REPORT} from '../../testing/evalReport';
import {EvalOverview} from './EvalOverview';

const GATES: EvalGate[] = [
  {
    name: 'Recall at 25',
    comparator: '>=',
    threshold: 0.85,
    threshold_text: '>= 0.85',
    value: 0.86,
    value_text: '0.86',
    status: 'pass',
    passed: true,
  },
  {
    name: 'Faithfulness',
    comparator: '>=',
    threshold: 0.9,
    threshold_text: '>= 0.90',
    value: 0.86,
    value_text: '0.86',
    status: 'fail',
    passed: false,
  },
];

describe('EvalOverview', () => {
  it('leads with the headline numbers and names the failed gate', () => {
    render(<EvalOverview report={parseReport(SAMPLE_REPORT)} gates={GATES} />);
    const tiles = screen.getByTestId('eval-tiles');
    expect(tiles).toHaveTextContent('1 of 2');
    expect(tiles).toHaveTextContent('Blocked by Faithfulness');
    expect(tiles).toHaveTextContent('$0.0936');
    expect(tiles).toHaveTextContent('32.2 s');
    // The threshold text already holds its comparator.
    expect(tiles).toHaveTextContent('gate >= 0.85');
    expect(tiles).not.toHaveTextContent('>= >=');
  });

  it('marks the rows below a gate and puts the weakest answer first', () => {
    render(<EvalOverview report={parseReport(SAMPLE_REPORT)} gates={GATES} />);
    const byType = screen.getByTestId('chart-recall-type');
    // "all" is the tile, not a bar.
    expect(within(byType).queryByText('all')).toBeNull();
    expect(within(byType).getByText('Gate: 0.85')).toBeInTheDocument();
    const answers = within(screen.getByTestId('chart-faithfulness'))
      .getAllByRole('button')
      .map(b => b.getAttribute('aria-label'));
    expect(answers).toEqual([
      'G-12: 0.50, trend',
      'G-01: 0.95, single_company',
    ]);
    const time = screen.getByTestId('chart-variant-time');
    expect(within(time).getByText('5.93 s')).toBeInTheDocument();
  });

  it('shows a tooltip on keyboard focus', () => {
    render(<EvalOverview report={parseReport(SAMPLE_REPORT)} gates={GATES} />);
    const bar = within(screen.getByTestId('chart-faithfulness')).getAllByRole(
      'button',
    )[0];
    if (bar === undefined) {
      throw new Error('no bar');
    }
    fireEvent.focus(bar);
    expect(screen.getByRole('tooltip')).toHaveTextContent('0.50G-12trend');
    fireEvent.blur(bar);
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});
