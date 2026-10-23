import {describe, expect, it} from 'vitest';

import type {Run} from '../state';
import {RESPONSE_1, RETRIEVAL_1} from '../testing/fixtures';
import {
  chipFor,
  fallbackChip,
  inlineChipFor,
  citedChunkIds,
  isChunkId,
  isCitationId,
  passageBody,
  quoteOf,
} from './citations';

const JPM = 'JPM_10K_2025-12-31__risk_factors__0003';
const FACT = 'facts:NVDA:Revenues:Q1FY2026';
const AAPL = 'AAPL_10Q_2022-12-31__risk_factors__0000';

function run(overrides: Partial<Run> = {}): Run {
  return {
    question: 'q',
    requestId: 'r',
    stepsLit: [],
    meta: null,
    analysis: null,
    retrieval: RETRIEVAL_1,
    deltas: [],
    findings: [],
    final: null,
    ...overrides,
  };
}

describe('isCitationId', () => {
  it('accepts chunk and fact IDs and rejects other text', () => {
    expect(isCitationId(JPM)).toBe(true);
    expect(isCitationId(FACT)).toBe(true);
    expect(isCitationId('note')).toBe(false);
    expect(isCitationId(`${JPM} x`)).toBe(false);
  });
});

describe('fallbackChip', () => {
  it('reads ticker, form, and year from a chunk ID', () => {
    expect(fallbackChip('AAPL_10K_2025-09-27__risk_factors__0000')).toEqual({
      label: 'AAPL 10-K 2025',
      source: 'AAPL 10-K period ending 2025, Risk Factors',
      fact: false,
    });
  });

  it('reads ticker and period from a fact ID', () => {
    expect(fallbackChip(FACT)).toEqual({
      label: 'NVDA facts Q1FY2026',
      source: 'NVDA XBRL company facts, Revenues Q1FY2026',
      fact: true,
    });
  });

  it('never returns a raw unknown ID as the label', () => {
    expect(fallbackChip('weird_id').label).toBe('weird');
  });
});

describe('inlineChipFor', () => {
  it('labels a retrieved chunk like a finding chip before final', () => {
    const chip = inlineChipFor(run(), JPM);
    expect(chip.label).toBe('JPM FY2025');
    expect(chip.source).toBe('JPMorgan Chase & Co. 10-K FY2025, Risk Factors');
    expect(chip.valid).toBe(true);
    expect(chip.label).toBe(chipFor(run(), JPM).label);
  });

  it('uses the resolved citation after final', () => {
    const chip = inlineChipFor(run({final: RESPONSE_1}), JPM);
    expect(chip.label).toBe('JPM FY2025');
    expect(chip.source).toBe('JPMorgan Chase & Co. 10-K FY2025, Risk Factors');
    expect(chip.valid).toBe(true);
  });

  it('labels a resolved fact with its ticker', () => {
    const final = {
      ...RESPONSE_1,
      citations_resolved: [
        {
          chunk_id: FACT,
          filing_name: 'NVDA 10-Q filed 2025-05-28',
          section_title: 'XBRL company facts',
          fiscal_label: 'Q1 FY2026',
          sec_url: null,
          valid: true,
          ticker: 'NVDA',
          kind: 'fact' as const,
        },
      ],
    };
    const chip = inlineChipFor(run({final}), FACT);
    expect(chip.label).toBe('NVDA facts Q1 FY2026');
    expect(chip.source).toBe('NVDA 10-Q filed 2025-05-28, XBRL company facts');
  });

  it('falls back to the ID and marks an unknown citation invalid', () => {
    const id = 'TSLA_10K_2025-12-31__mdna__0001';
    const before = inlineChipFor(run(), id);
    expect(before.label).toBe('TSLA 10-K 2025');
    expect(before.valid).toBe(false);
    expect(inlineChipFor(run({final: RESPONSE_1}), id).valid).toBe(false);
  });
});

describe('location in the chip source', () => {
  it('names the part and item when the citation has a location', () => {
    const chip = inlineChipFor(run({final: RESPONSE_1}), AAPL);
    expect(chip.source).toBe(
      'Apple Inc. 10-Q Q1 FY2023, Part II, Item 1A. Risk Factors',
    );
  });
});

describe('passageBody', () => {
  it('drops the prefix line of a chunk text', () => {
    expect(passageBody('Apple Inc | 10-K | FY2025 | Risk Factors\nBody.')).toBe(
      'Body.',
    );
    expect(passageBody('No prefix\nBody.')).toBe('No prefix\nBody.');
    expect(passageBody('One line')).toBe('One line');
  });
});

describe('reader order', () => {
  it('lists the cited chunk IDs once, without facts', () => {
    const final = {
      ...RESPONSE_1,
      citations_resolved: [
        ...RESPONSE_1.citations_resolved,
        {...RESPONSE_1.citations_resolved[0]!},
        {
          ...RESPONSE_1.citations_resolved[0]!,
          chunk_id: FACT,
          kind: 'fact' as const,
        },
      ],
    };
    expect(citedChunkIds(run({final}))).toEqual([AAPL, JPM]);
    expect(citedChunkIds(run())).toEqual([]);
    expect(isChunkId(FACT)).toBe(false);
    expect(quoteOf(run({final: RESPONSE_1}), AAPL)).toBe(
      'The Company depends on component suppliers in Asia.',
    );
  });
});
