import {fireEvent, render, screen, within} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {SCALES, periodsOf} from '../../lib/financials';
import {FIN_NVDA_QUARTERLY} from '../../testing/financials';
import {LineItemTable} from './LineItemTable';

const income = FIN_NVDA_QUARTERLY.statements[0]?.items ?? [];
const periods = periodsOf(income);

function draw(
  checked: ReadonlyMap<string, number>,
  expanded: ReadonlySet<string> = new Set(),
) {
  const onToggleCheck = vi.fn();
  const onToggleExpand = vi.fn();
  render(
    <LineItemTable
      items={income}
      periods={periods}
      checked={checked}
      expanded={expanded}
      usdScale={SCALES.M}
      sharesScale={SCALES.M}
      sources={FIN_NVDA_QUARTERLY.sources}
      onToggleCheck={onToggleCheck}
      onToggleExpand={onToggleExpand}
    />,
  );
  return {onToggleCheck, onToggleExpand};
}

function row(id: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(`[data-row="${id}"]`);
  if (found === null) {
    throw new Error(`no row ${id}`);
  }
  return found;
}

describe('LineItemTable', () => {
  it('lists the rows with 1 column per period, in millions', () => {
    draw(new Map([['revenue', 1]]));
    expect(
      screen.getAllByRole('columnheader').map(th => th.textContent),
    ).toEqual([
      'Breakdown',
      'Q1 FY2025',
      'Q2 FY2025',
      'Q3 FY2025',
      'Q4 FY2025',
    ]);
    expect(within(row('revenue')).getByText('26,044')).toBeInTheDocument();
    expect(within(row('eps_diluted')).getByText('$0.78')).toBeInTheDocument();
    // The child row stays hidden until its parent opens.
    expect(document.querySelector('[data-row="rnd"]')).toBeNull();
  });

  it('colors a checked box with its series slot', () => {
    draw(new Map([['net_income', 3]]));
    const box = within(row('net_income')).getByRole('checkbox');
    expect(box).toHaveAttribute('aria-checked', 'true');
    expect(box.getAttribute('style')).toContain('var(--k-s3)');
    expect(within(row('revenue')).getByRole('checkbox')).toHaveAttribute(
      'aria-checked',
      'false',
    );
  });

  it('toggles a row and opens a parent', () => {
    const {onToggleCheck, onToggleExpand} = draw(new Map());
    fireEvent.click(within(row('opex')).getByRole('checkbox'));
    expect(onToggleCheck).toHaveBeenCalledWith('opex');
    fireEvent.click(
      screen.getByRole('button', {name: 'Expand Operating expenses'}),
    );
    expect(onToggleExpand).toHaveBeenCalledWith('opex');
  });

  it('shows the children of an expanded row, indented', () => {
    draw(new Map(), new Set(['opex']));
    expect(row('rnd')).toBeInTheDocument();
    expect(
      screen.getByRole('button', {name: 'Collapse Operating expenses'}),
    ).toHaveAttribute('aria-expanded', 'true');
  });

  it('marks a derived value and names its filing', () => {
    draw(new Map());
    const cells = within(row('revenue')).getAllByRole('cell');
    const q4 = cells[3];
    expect(q4).toHaveAttribute('data-derived', 'true');
    expect(q4).toHaveClass('fin-derived');
    expect(q4?.getAttribute('title')).toContain(
      'Derived: fiscal year minus the nine-month year-to-date',
    );
    expect(cells[0]?.getAttribute('title')).toContain(
      '10-Q filed Nov 20, 2024',
    );
  });

  it('disables the unchecked boxes when 8 series are charted', () => {
    const full = new Map(
      ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map((id, i) => [id, i + 1]),
    );
    const {onToggleCheck} = draw(full);
    const box = within(row('revenue')).getByRole('checkbox');
    expect(box).toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(box);
    expect(onToggleCheck).not.toHaveBeenCalled();
  });
});
