/**
 * Plain-language notes on each answer prompt version, from
 * `docs/PROMPT_LOG.md`: what changed, why, what the measurement showed,
 * and which rules changed in meaning (the others were only reworded). A
 * version without a note here still shows its rule changes.
 */

/** The note of 1 prompt version. */
export interface PromptNote {
  readonly title: string;
  readonly what: string;
  readonly why: string;
  readonly result: string;
  /** Kept in use after the test, rejected, or the first version. */
  readonly outcome: 'first' | 'kept' | 'rejected';
  /** The parts whose meaning changed, by key (`rule:7`, `user`). */
  readonly meaning: readonly string[];
}

const NOTES: Readonly<Record<string, PromptNote>> = {
  '1.0.0': {
    title: 'The first measured prompt',
    what: 'The prompt of chapter 12: 21 rules on grounding every claim in the filings, copying numbers exactly, listing gaps, and the shape of the answer.',
    why: 'The starting point. The length rules (17, 18, 20, 21) were tightened before release, after the first test answers ran out of room at 4,000 output tokens.',
    result:
      'On the 2 example questions every citation was valid, at about $0.12 to $0.14 per answer.',
    outcome: 'first',
    meaning: [],
  },
  '1.1.0': {
    title: 'Label every period with its fiscal year and end date',
    what: 'Rule 7 now asks for the fiscal label and end date on every period ("Q3 fiscal 2026, ended October 26, 2025"), bans bare years such as "2024", and asks for each company\'s own fiscal period.',
    why: "Companies end their fiscal years in different months, so a bare year is unclear: NVIDIA's fiscal 2025 ended in January 2025.",
    result:
      'Every period in the test answers carried its label; citations stayed 100% valid; answers grew 2% to 15% longer.',
    outcome: 'kept',
    meaning: ['rule:7'],
  },
  '1.2.0': {
    title: 'Say what the filings cannot show',
    what: 'Rule 13 now asks the answer to list, under gaps, each company with only 1 annual report (so no change over time can be shown) and each company whose filings state no response to the risk asked about.',
    why: 'Earlier answers left these limits unsaid, so a comparison could read as complete when it was not.',
    result:
      'The pharma answer named the single 10-K of MRK, LLY, and ABBV and the companies with no stated response; 1.0.0 and 1.1.0 named neither.',
    outcome: 'kept',
    meaning: ['rule:13'],
  },
  '1.3.0': {
    title: 'Structured output instead of a tool call',
    what: 'The answer now comes back as structured output that must match the answer schema, instead of a tool call. Rule 16 says to return 1 JSON object.',
    why: 'The model may skip an optional tool call and answer in plain text, which breaks the answer format; the provider enforces structured output.',
    result:
      'Every test answer matched the schema; the answer still streamed with the direct answer first, and prompt caching kept working.',
    outcome: 'kept',
    meaning: ['rule:16'],
  },
  '1.4.0': {
    title: 'Use the exact reported numbers',
    what: 'A new section, COMPANY FACTS (rule 22), and a <facts> block in the user message: for a number question the prompt now carries the values the company reported in its XBRL data, and the answer copies those values and cites them.',
    why: 'Filing prose rounds numbers ("$130.5 billion"); the reported facts hold the exact value ("$130,497 million").',
    result:
      'The NVIDIA revenue answer gave the exact reported values with their fact IDs; all 5 citations were valid.',
    outcome: 'kept',
    meaning: ['heading:COMPANY FACTS', 'rule:22', 'user'],
  },
  '1.5.0': {
    title: 'Claim only what the cited passages say',
    what: 'Rules 3, 7, 11, and 17 now hold each sentence to its citations: every part of a sentence must come from a passage it cites (3); a prior-year end date only when a cited passage states it (7); a claim that something changed since last year cites both years (11); a theme shared by companies cites each company (17). The other rules were reworded shorter, with the same meaning, to keep the prompt within its size limit.',
    why: 'The judge traced most partly supported claims in the 1.4.0 eval to 3 habits: change claims citing only the later filing, end dates read from uncited passages, and theme lists wider than their citations.',
    result:
      'Faithfulness rose from 0.895 to 0.918, but adversarial test G-28 failed: a finding cited a planted passage that holds instructions to the model. Rejected; 1.4.0 stayed in use.',
    outcome: 'rejected',
    meaning: ['rule:3', 'rule:7', 'rule:11', 'rule:17'],
  },
  '1.5.1': {
    title: 'Never cite a passage that gives the model instructions',
    what: '1.5.0 plus 1 sentence in rule 4: a finding never cites a passage that holds instructions to the model; the direct answer may mention such text without citing it. A few rules and the opening were reworded shorter.',
    why: '1.5.0 failed test G-28 because a finding cited the planted instruction passage to point it out.',
    result:
      'Faithfulness 0.926 (0.895 with 1.4.0), citation precision 0.998, every gate passed, and both adversarial tests passed. It replaced 1.4.0, so it also carries the 1.5.0 changes.',
    outcome: 'kept',
    meaning: ['rule:4'],
  },
};

/**
 * The note of a prompt version.
 *
 * @param version The version, such as `1.5.1`.
 * @return The note, or null for a version without one.
 */
export function noteFor(version: string): PromptNote | null {
  return NOTES[version] ?? null;
}
