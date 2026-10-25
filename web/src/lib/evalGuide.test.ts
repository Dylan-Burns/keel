import {describe, expect, it} from 'vitest';

import {guideFor} from './evalGuide';

/** Every heading `keel eval` writes (keel/evaluation/report.py). */
const HEADINGS = [
  'Eval report',
  'Regression gates',
  'Retrieval metrics (hybrid)',
  'Ablation: retrieval mode and reranker (chapter 18.7)',
  'Out-of-scope questions',
  'Per question (hybrid)',
  'Weakest questions',
  'Answer metrics (chapter 18.4 and 18.6)',
  'Per question (answers)',
  'Weakest answers',
];

describe('evalGuide', () => {
  it('has a note for every section of the report', () => {
    for (const heading of HEADINGS) {
      const guide = guideFor(heading);
      expect(guide, heading).not.toBeNull();
      expect(guide?.terms.length, heading).toBeGreaterThan(0);
    }
  });

  it('tells the 2 per-question tables apart', () => {
    const search = guideFor('Per question (hybrid)');
    const answers = guideFor('Per question (answers)');
    expect(search?.terms.map(([t]) => t)).toContain('Retrieval ms');
    expect(answers?.terms.map(([t]) => t)).toContain('Faithfulness');
  });

  it('has no note for text before a heading or an unknown section', () => {
    expect(guideFor(null)).toBeNull();
    expect(guideFor('Prompt log')).toBeNull();
  });
});
