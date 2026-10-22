import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {RESPONSE_1} from '../testing/fixtures';
import {runOf} from '../testing/runs';
import {FindingsGroup} from './FindingsGroup';

const JPM = RESPONSE_1.answer.company_findings[1];

describe('FindingsGroup', () => {
  it('shows the findings with clickable chips and unverified marks after final', () => {
    if (JPM === undefined) {
      throw new Error('fixture');
    }
    const onSelect = vi.fn();
    render(
      <FindingsGroup
        run={runOf(RESPONSE_1)}
        company={JPM}
        onSelectCitation={onSelect}
      />,
    );
    expect(screen.getByText('JPMorgan Chase & Co. (JPM)')).toBeInTheDocument();
    expect(screen.getByTestId('citation-unverified')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('citation-chip'));
    expect(onSelect).toHaveBeenCalledWith(JPM.findings[0]?.citations[0]);
  });

  it('keeps the chips off while streaming', () => {
    if (JPM === undefined) {
      throw new Error('fixture');
    }
    render(
      <FindingsGroup
        run={runOf(RESPONSE_1, 9)}
        company={JPM}
        onSelectCitation={vi.fn()}
      />,
    );
    expect(screen.getByTestId('citation-chip')).toBeDisabled();
  });
});
