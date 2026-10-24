import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {FIN_COMPANIES} from '../../testing/financials';
import {CompanyPicker} from './CompanyPicker';
import {PeriodToggle} from './PeriodToggle';
import {RangeSlider} from './RangeSlider';
import {StatementTabs} from './StatementTabs';
import {UnitToggle} from './UnitToggle';

describe('financials controls', () => {
  it('PeriodToggle presses the period and reports a change', () => {
    const onChange = vi.fn();
    render(<PeriodToggle period="annual" onChange={onChange} />);
    expect(screen.getByRole('button', {name: 'Annual'})).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    fireEvent.click(screen.getByRole('button', {name: 'Quarterly'}));
    expect(onChange).toHaveBeenCalledWith('quarterly');
  });

  it('UnitToggle presses the unit and reports a change', () => {
    const onChange = vi.fn();
    render(<UnitToggle unit="auto" onChange={onChange} />);
    expect(screen.getByRole('button', {name: 'Auto'})).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    fireEvent.click(screen.getByRole('button', {name: 'B'}));
    expect(onChange).toHaveBeenCalledWith('B');
  });

  it('StatementTabs selects a tab by click and by arrow key', () => {
    const onSelect = vi.fn();
    render(
      <StatementTabs
        tabs={[
          {id: 'income', label: 'Income Statement'},
          {id: 'balance', label: 'Balance Sheet'},
          {id: 'cash', label: 'Cash Flow'},
        ]}
        selected="income"
        onSelect={onSelect}
      />,
    );
    expect(screen.getByRole('tab', {name: 'Income Statement'})).toHaveAttribute(
      'aria-selected',
      'true',
    );
    fireEvent.click(screen.getByRole('tab', {name: 'Cash Flow'}));
    expect(onSelect).toHaveBeenCalledWith('cash');
    fireEvent.keyDown(screen.getByRole('tab', {name: 'Income Statement'}), {
      key: 'ArrowLeft',
    });
    expect(onSelect).toHaveBeenLastCalledWith('cash');
    fireEvent.keyDown(screen.getByRole('tab', {name: 'Income Statement'}), {
      key: 'ArrowRight',
    });
    expect(onSelect).toHaveBeenLastCalledWith('balance');
  });

  it('CompanyPicker lists the companies and reports a pick', () => {
    const onChange = vi.fn();
    render(
      <CompanyPicker
        companies={FIN_COMPANIES.companies}
        ticker="NVDA"
        onChange={onChange}
      />,
    );
    const select = screen.getByRole('combobox', {name: 'Company'});
    expect(select).toHaveValue('NVDA');
    expect(screen.getAllByRole('option')).toHaveLength(3);
    fireEvent.change(select, {target: {value: 'JPM'}});
    expect(onChange).toHaveBeenCalledWith('JPM');
  });

  it('RangeSlider keeps the thumbs in order', () => {
    const onChange = vi.fn();
    render(
      <RangeSlider
        count={10}
        low={4}
        high={9}
        labelOf={i => `FY${2016 + i}`}
        onChange={onChange}
      />,
    );
    expect(screen.getByTestId('fin-range')).toHaveTextContent('FY2020');
    fireEvent.change(screen.getByRole('slider', {name: 'First period'}), {
      target: {value: '2'},
    });
    expect(onChange).toHaveBeenLastCalledWith(2, 9);
    fireEvent.change(screen.getByRole('slider', {name: 'Last period'}), {
      target: {value: '3'},
    });
    expect(onChange).toHaveBeenLastCalledWith(4, 4);
  });
});
