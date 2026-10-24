import {act, fireEvent, render, screen, within} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {periodsOf} from '../../lib/financials';
import {FIN_NVDA_QUARTERLY} from '../../testing/financials';
import {StatementCharts} from './StatementCharts';

const income = FIN_NVDA_QUARTERLY.statements[0]?.items ?? [];

function draw(checked: ReadonlyMap<string, number>): void {
  render(
    <StatementCharts
      items={income}
      checked={checked}
      periods={periodsOf(income)}
      unit="auto"
      sources={FIN_NVDA_QUARTERLY.sources}
    />,
  );
}

describe('StatementCharts', () => {
  it('asks for a row when nothing is checked', () => {
    draw(new Map());
    expect(screen.getByTestId('fin-chart-empty')).toHaveTextContent(
      'Check a line item',
    );
  });

  it('draws 1 bar per checked row and period, derived bars faded', () => {
    draw(
      new Map([
        ['revenue', 1],
        ['net_income', 2],
      ]),
    );
    const charts = screen.getAllByTestId('fin-chart');
    expect(charts).toHaveLength(1);
    expect(charts[0]).toHaveAttribute('data-series', '2');
    const bars = screen.getAllByTestId('fin-bar');
    expect(bars).toHaveLength(8);
    const revenue = bars.filter(
      b => b.getAttribute('data-series-id') === 'revenue',
    );
    expect(revenue[0]?.getAttribute('style')).toContain('var(--k-s1)');
    expect(revenue[3]?.getAttribute('style')).toContain('fill-opacity: 0.55');
    expect(within(charts[0]!).getByText("Q3 '25")).toBeInTheDocument();
    expect(screen.getByTestId('fin-legend')).toHaveTextContent(
      'Total revenueNet income',
    );
  });

  it('stacks 1 chart per unit', () => {
    draw(
      new Map([
        ['revenue', 1],
        ['eps_diluted', 2],
      ]),
    );
    const charts = screen.getAllByTestId('fin-chart');
    expect(charts.map(c => c.getAttribute('data-unit'))).toEqual([
      'USD',
      'USD/shares',
    ]);
    expect(screen.getByText('USD per share')).toBeInTheDocument();
  });

  it('shows every series of a period with its filing, and pins', () => {
    draw(
      new Map([
        ['revenue', 1],
        ['eps_diluted', 2],
      ]),
    );
    const bands = screen.getAllByTestId('fin-band');
    fireEvent.pointerMove(bands[3]!, {clientX: 100, clientY: 100});
    const tip = screen.getByTestId('fin-tooltip');
    expect(tip).toHaveAttribute('data-pinned', 'false');
    expect(tip).toHaveTextContent('Q4 FY2025');
    expect(tip).toHaveTextContent('Oct 28, 2024 to Jan 26, 2025');
    const rows = within(tip).getAllByTestId('fin-tooltip-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('$39.33B');
    expect(rows[0]).toHaveTextContent('10-K filed Feb 26, 2025');
    expect(rows[0]).toHaveTextContent('DERIVED');
    expect(
      within(rows[0]!).getByRole('link', {name: 'filing'}),
    ).toHaveAttribute('href', FIN_NVDA_QUARTERLY.sources[0]?.url);
    fireEvent.pointerLeave(bands[3]!);
    expect(screen.queryByTestId('fin-tooltip')).toBeNull();

    fireEvent.click(bands[1]!, {clientX: 50, clientY: 50});
    expect(screen.getByTestId('fin-tooltip')).toHaveAttribute(
      'data-pinned',
      'true',
    );
    // A pinned tooltip ignores hover elsewhere and closes on Escape.
    fireEvent.pointerMove(bands[2]!, {clientX: 60, clientY: 60});
    expect(screen.getByTestId('fin-tooltip')).toHaveTextContent('Q2 FY2025');
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));
    });
    expect(screen.queryByTestId('fin-tooltip')).toBeNull();
  });

  it('works from the keyboard', () => {
    draw(new Map([['revenue', 1]]));
    const bands = screen.getAllByTestId('fin-band');
    act(() => bands[0]!.focus());
    expect(screen.getByTestId('fin-tooltip')).toHaveTextContent('Q1 FY2025');
    fireEvent.keyDown(bands[0]!, {key: 'ArrowRight'});
    expect(document.activeElement).toBe(bands[1]);
    fireEvent.keyDown(bands[1]!, {key: 'Enter'});
    const tip = screen.getByTestId('fin-tooltip');
    expect(tip).toHaveAttribute('data-pinned', 'true');
    fireEvent.click(within(tip).getByRole('button', {name: 'Close'}));
    expect(screen.queryByTestId('fin-tooltip')).toBeNull();
  });
});
