import {describe, expect, it} from 'vitest';

import type {QuestionTemplate} from '../api/types';
import {fillTemplate} from './templates';

const RISK: QuestionTemplate = {
  id: 'risk_benchmark',
  label: 'Risk benchmark',
  text: 'What are the primary risk factors facing {companies} in {period}, and how do they compare?',
  default_period: 'the latest fiscal year',
};

describe('fillTemplate', () => {
  it('fills the companies and the period', () => {
    expect(fillTemplate(RISK, ' Apple and  Tesla ', 'fiscal 2025')).toBe(
      'What are the primary risk factors facing Apple and Tesla in fiscal 2025, and how do they compare?',
    );
  });

  it('takes the default period and keeps braces in a value as text', () => {
    expect(fillTemplate(RISK, '{period}', '')).toBe(
      'What are the primary risk factors facing {period} in the latest fiscal year, and how do they compare?',
    );
  });

  it('refuses an empty or too long companies field', () => {
    expect(fillTemplate(RISK, '   ', 'x')).toBeNull();
    expect(fillTemplate(RISK, 'A'.repeat(301), 'x')).toBeNull();
    expect(fillTemplate(RISK, 'Apple', 'B'.repeat(301))).toBeNull();
    expect(fillTemplate({...RISK, text: 'no slot'}, 'Apple', '')).toBeNull();
  });
});
