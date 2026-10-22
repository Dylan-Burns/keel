import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {RESPONSE_2} from '../testing/fixtures';
import {runOf} from '../testing/runs';
import {ProgressSteps} from './ProgressSteps';

function step(name: string): HTMLElement {
  const found = screen
    .getByTestId('progress-steps')
    .querySelector(`[data-step="${name}"]`);
  if (!(found instanceof HTMLElement)) {
    throw new Error(name);
  }
  return found;
}

describe('ProgressSteps', () => {
  it('lights the steps in order and pulses the last one', () => {
    render(<ProgressSteps run={runOf(RESPONSE_2, 2)} streaming={false} />);
    expect(step('understanding')).toHaveAttribute('data-lit', 'true');
    expect(step('retrieval')).toHaveAttribute('data-active', 'true');
    expect(step('model')).toHaveAttribute('data-lit', 'false');
  });

  it('stops the pulse on the first delta', () => {
    render(<ProgressSteps run={runOf(RESPONSE_2, 4)} streaming />);
    expect(step('model')).toHaveAttribute('data-lit', 'true');
    expect(step('model')).toHaveAttribute('data-active', 'false');
  });
});
