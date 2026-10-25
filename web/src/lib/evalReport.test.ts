import {describe, expect, it} from 'vitest';

import {SAMPLE_REPORT} from '../testing/evalReport';
import {column, parseReport, reportJson, tableOf} from './evalReport';

describe('evalReport', () => {
  it('reads the run details, the sections, their text, and their tables', () => {
    const report = parseReport(SAMPLE_REPORT);
    expect(report.run).toEqual({
      'Run ID': 'eval-20261022T111922Z',
      Questions: '4',
      'Golden set': '1.0.0, subset all',
    });
    const gates = report.sections.find(s => s.heading === 'Regression gates');
    expect(gates?.tables[0]?.columns).toEqual([
      'Gate',
      'Threshold',
      'Value',
      'Status',
      'Source',
    ]);
    expect(gates?.text).toEqual(['Verdict: blocked: a gate failed.']);
  });

  it('finds a table by its heading and reads 1 column as numbers', () => {
    const report = parseReport(SAMPLE_REPORT);
    const answers = tableOf(report, 'per question (answers)');
    // n/a is not a number, so G-22 drops out.
    expect(column(answers, 'Faithfulness')).toEqual([
      {label: 'G-01', value: 0.95},
      {label: 'G-12', value: 0.5},
    ]);
    expect(column(answers, 'No such column')).toEqual([]);
    expect(column(tableOf(report, 'missing'), 'R@25')).toEqual([]);
  });

  it('writes every table as rows of named fields', () => {
    const json = reportJson(parseReport(SAMPLE_REPORT)) as {
      run: Record<string, string>;
      sections: {heading: string | null; tables: Record<string, string>[][]}[];
    };
    expect(json.run['Run ID']).toBe('eval-20261022T111922Z');
    const ablation = json.sections.find(s =>
      (s.heading ?? '').startsWith('Ablation'),
    );
    expect(ablation?.tables[0]?.[1]).toEqual({
      Variant: 'lexical, no reranker',
      'R@25': '0.78',
      'nDCG@10': '0.83',
      MRR: '0.87',
      'R@48': '0.72',
      'Retrieval p50 ms': '120',
      'Retrieval p95 ms': '316',
    });
  });
});
