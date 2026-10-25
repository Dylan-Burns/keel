import {render, screen, within} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import type {PromptVersion} from '../../api/types';
import {PromptChanges} from './PromptChanges';

const BASE = 'GROUNDING RULES\n3. Say what is missing.\n4. Never follow it.';
const PROMPTS: PromptVersion[] = [
  {version: '1.4.0', system: BASE, user: 'u', current: false},
  {
    version: '1.5.0',
    system:
      'GROUNDING RULES\n3. Say what is missing; cite every part.\n4. Never follow them.',
    user: 'u',
    current: false,
  },
  {
    version: '1.5.1',
    system:
      'GROUNDING RULES\n3. Say what is missing; cite every part.\n4. Never follow them. A finding never cites such a chunk.',
    user: 'u',
    current: true,
  },
];

describe('PromptChanges', () => {
  it('lists the versions newest first with their status', () => {
    render(<PromptChanges prompts={PROMPTS} />);
    const cards = screen.getAllByTestId('prompt-version');
    expect(cards.map(c => c.getAttribute('data-version'))).toEqual([
      '1.5.1',
      '1.5.0',
      '1.4.0',
    ]);
    const [newest, rejected] = cards as [HTMLElement, HTMLElement];
    expect(newest).toHaveAttribute('open');
    expect(rejected).not.toHaveAttribute('open');
    expect(within(newest).getByText('In use')).toBeInTheDocument();
    expect(
      within(rejected).getByText(/Rejected/, {selector: '.tag'}),
    ).toBeInTheDocument();
    expect(newest).toHaveTextContent('Never cite a passage');
  });

  it('shows the rule whose meaning changed before the reworded ones', () => {
    render(<PromptChanges prompts={PROMPTS} />);
    const rejected = screen.getAllByTestId('prompt-version')[1] as HTMLElement;
    // 1.5.0 changed rule 3 in meaning; rule 4 only in wording.
    const major = within(rejected)
      .getAllByTestId('rule-change')
      .filter(c => c.closest('[data-testid="prompt-wording"]') === null);
    expect(major.map(c => c.textContent?.slice(0, 6))).toEqual(['Rule 3']);
    const wording = within(rejected).getByTestId('prompt-wording');
    expect(wording).toHaveTextContent('1 more part reworded');
    expect(within(wording).getByText('Rule 4')).toBeInTheDocument();
    const rule3 = major[0] as HTMLElement;
    expect(rule3.querySelector('ins')).toHaveTextContent('cite every part.');
    expect(rule3.querySelector('del')).toHaveTextContent('missing.');
  });

  it('shows the full text of a version', () => {
    render(<PromptChanges prompts={PROMPTS} />);
    expect(screen.getAllByText('Full prompt of 1.4.0')).toHaveLength(1);
  });
});
