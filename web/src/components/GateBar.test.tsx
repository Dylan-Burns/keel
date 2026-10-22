import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import type {EvalGate} from '../api/types';
import {EVAL_PAGE} from '../testing/fixtures';
import {GateBar, gateScale} from './GateBar';

const RECALL = EVAL_PAGE.gates[0] as EvalGate;

describe('GateBar', () => {
  it('places a fraction gate and a latency gate on their bars', () => {
    expect(gateScale(RECALL)).toEqual({fill: 0.63, mark: 0.85});
    const latency: EvalGate = {
      ...RECALL,
      comparator: '<=',
      threshold: 40,
      value: 30,
    };
    expect(gateScale(latency)).toEqual({fill: 0.375, mark: 0.5});
    expect(gateScale({...RECALL, value: null}).fill).toBe(0);
    expect(gateScale({...latency, threshold: 0, value: 0})).toEqual({
      fill: 0,
      mark: 0,
    });
  });

  it('is red at once with reduced motion when the gate fails', () => {
    render(
      <ul>
        <GateBar gate={RECALL} reduced />
      </ul>,
    );
    expect(screen.getByTestId('eval-gate')).toHaveAttribute('data-red', 'true');
  });
});
