/**
 * Plain-language notes for each section of the eval report: what the
 * section shows, how to read it, and what each column means. The eval page
 * shows the note under the section heading. Definitions follow chapter 18.
 */

/** The note of 1 report section. */
export interface SectionGuide {
  /** What the section shows, in 1 or 2 sentences. */
  readonly summary: string;
  /** What a good result looks like. */
  readonly good?: string;
  /** Each column or term, with its meaning. */
  readonly terms: readonly (readonly [string, string])[];
}

const QUESTION = [
  'Question',
  'The ID of a test question from the golden set, such as G-04. The golden set is a fixed list of questions with known good sources, so runs can be compared over time.',
] as const;

const TYPE = [
  'Type',
  'The kind of question: single_company (1 company), comparison (2 or more companies side by side), trend (1 company over several periods), numeric (asks for a number), sector (a whole industry), ambiguous_entity (a name that could mean more than 1 company), adversarial (tries to trick the model), out_of_corpus (a company or topic Keel does not cover).',
] as const;

const RECALL = [
  'R@10, R@25, R@48',
  'Recall at 10, 25, or 48: of the passages that should have been found, the share that appear in the top 10, 25, or 48 results. 1.00 means every right passage was found; 0.50 means half were.',
] as const;

const MRR = [
  'MRR',
  'Mean reciprocal rank: how high the first right passage ranks. 1.00 means it was always the top result; 0.50 means it was second on average.',
] as const;

const NDCG = [
  'nDCG@10',
  'Ranking quality of the top 10 results, where more useful passages count more and higher positions count more. 1.00 is the best possible order.',
] as const;

const COVERAGE = [
  'Coverage',
  'For questions about 2 or more companies: the share of the companies that got at least 1 relevant passage. n/a when the question names 1 company.',
] as const;

const FAITHFULNESS = [
  'Faithfulness',
  'The share of statements in the answer that the cited filing text supports, as graded by a separate judge model. 1.00 means every statement is backed by its source.',
] as const;

const PRECISION = [
  'Citation precision',
  'The share of citations whose passage supports the claim it is attached to. A low value means the answer points at the wrong passages.',
] as const;

const GUIDES: readonly (readonly [string, SectionGuide])[] = [
  [
    'eval report',
    {
      summary:
        'The run details: when the test ran, on which questions, with which search index, prompt, and models. Two runs are comparable only when these match.',
      terms: [
        ['Run ID', 'The name of this test run, with its start time.'],
        [
          'Golden set',
          'The version of the test question list, and whether all of it ran.',
        ],
        [
          'Index',
          'The version of the search index of filing passages that answered the questions.',
        ],
        [
          'Index chunks_sha256',
          'A fingerprint of the index contents. A different value means the passages changed.',
        ],
        [
          'Labels from another index',
          'Whether the known good sources were matched from an older index. "none" means they belong to this one.',
        ],
        [
          'Prompt version',
          'The version of the instructions sent to the answer model.',
        ],
        ['Answer model', 'The model that wrote the answers.'],
        [
          'Judge model',
          'A different model that grades the answers, so the answer model never grades itself.',
        ],
        [
          'Model requests',
          'How many calls went to the answer model and to the judge.',
        ],
        [
          'Variants',
          'The search setups that ran, for the comparison in the ablation section.',
        ],
        ['Wall time', 'How long the whole run took, in seconds.'],
      ],
    },
  ],
  [
    'regression gates',
    {
      summary:
        'The pass or fail checks for a release. Each gate compares 1 measured value with a fixed target. If any gate fails, the verdict line says the release is blocked.',
      good: 'Every row says pass. A "pending" gate had too few graded answers to judge and does not block.',
      terms: [
        ['Gate', 'The quality check, defined in the rows below.'],
        [
          'Threshold',
          'The target. ">= 0.85" means the value must be 0.85 or more; "<= 40 s" means at most 40 seconds.',
        ],
        ['Value', 'What this run measured.'],
        ['Status', 'pass, fail, or pending.'],
        [
          'Source',
          'Where the value comes from: the search step, the judge model, or code checks.',
        ],
        ['Recall at 25', 'Search finds the right passages (see R@25 below).'],
        ['MRR', 'The first right passage ranks near the top.'],
        ['Faithfulness', 'Answers say only what their sources support.'],
        [
          'Citation precision',
          'Citations point at passages that back the claim.',
        ],
        [
          'Coverage completeness',
          'Comparison and sector answers cover every company asked about, or say which one is missing.',
        ],
        [
          'Numeric accuracy',
          'Numbers in answers match the filings within 0.5%.',
        ],
        ['Schema validity', 'Every answer has the required structure.'],
        [
          'Refusal correctness',
          'Questions outside the filings are declined without calling the model.',
        ],
        ['Latency p95', '95% of answers finish within this many seconds.'],
        [
          'Mean cost per question',
          'The average model cost of 1 answer, in US dollars.',
        ],
      ],
    },
  ],
  [
    'retrieval metrics',
    {
      summary:
        'How well the search step finds the right filing passages before the model writes anything, by type of question. The first row ("all") is every question together.',
      good: 'Values near 1.00. The gate for R@25 is 0.85.',
      terms: [
        TYPE,
        ['Questions', 'How many questions of that type ran.'],
        RECALL,
        MRR,
        NDCG,
        COVERAGE,
        [
          'Metric notes',
          'The paragraph under the table states the exact rules, for reference.',
        ],
      ],
    },
  ],
  [
    'ablation',
    {
      summary:
        'An experiment: the same questions searched 6 ways, to show what each part of search adds. Lexical matches words, dense matches meaning, hybrid combines both, and the reranker re-orders the top results with a second model.',
      good: 'The setup Keel uses (hybrid with the reranker) should score highest. The reranker costs time, which the millisecond columns show.',
      terms: [
        ['Variant', 'The search setup.'],
        ['R@25, R@48', 'Recall at 25 and 48 (see the retrieval section).'],
        NDCG,
        MRR,
        [
          'Retrieval p50 ms',
          'The typical search time in milliseconds: half the questions were faster.',
        ],
        [
          'Retrieval p95 ms',
          'The slow-case search time: 95% of questions were faster.',
        ],
      ],
    },
  ],
  [
    'out-of-scope',
    {
      summary:
        'Questions Keel should decline, such as a company it does not cover. Keel must refuse them before calling the model, so they cost nothing.',
      good: 'Every outcome is "refused".',
      terms: [
        QUESTION,
        TYPE,
        ['Outcome', '"refused" is correct here; anything else is a miss.'],
        [
          'Reason',
          'Why it was refused: unknown_company (not in the filings), out_of_scope_request (not a filings question), not_indexed (a real company whose filings are not loaded).',
        ],
      ],
    },
  ],
  [
    'per question (hybrid)',
    {
      summary:
        'The search results of each test question, 1 row per question, with the setup Keel uses.',
      good: 'R@25 near 1.00 on every row. A low row shows which question the search struggles with.',
      terms: [
        QUESTION,
        TYPE,
        [
          'Outcome',
          '"scored" means the question was searched and graded; "refused" means Keel declined it; "answer_only" means the question has no known good passages, so only its answer is graded (in the answer sections).',
        ],
        [
          'Labels',
          'How the right answers are marked: chunk (exact passages) or section (any passage of the right filing section).',
        ],
        ['Chunks', 'How many passages search returned.'],
        ['Relevant', 'How many of them are right ones.'],
        ['R@25', 'Recall at 25 for this question.'],
        MRR,
        NDCG,
        COVERAGE,
        ['Retrieval ms', 'How long the search took, in milliseconds.'],
      ],
    },
  ],
  [
    'weakest questions',
    {
      summary:
        'The questions where search found the fewest right passages, worst first, with where the right passages are and where search looked instead.',
      terms: [
        QUESTION,
        ['R@25', 'Recall at 25 for this question.'],
        [
          'Expected sources',
          "The filings and sections that hold the right passages, such as DIS_10K_2024-09-28 mdna (the management discussion of Disney's 2024 annual report).",
        ],
        [
          'Context sections',
          'The sections search actually returned, with how many passages each. When these differ from the expected sources, search looked in the wrong place.',
        ],
        ['Note', 'Any remark about the question.'],
      ],
    },
  ],
  [
    'answer metrics',
    {
      summary:
        'The quality, speed, and cost of the written answers, by type of question. A separate judge model grades each statement against the filing text it cites.',
      good: 'Faithfulness and citation precision of 0.90 or more; coverage, numeric, and schema at 1.00.',
      terms: [
        TYPE,
        ['Questions', 'How many questions of that type ran.'],
        [
          'Questions with a call',
          'How many reached the model. Declined questions make no call.',
        ],
        FAITHFULNESS,
        PRECISION,
        COVERAGE,
        [
          'Numeric',
          'For number questions: the share whose value matches the filing within 0.5%.',
        ],
        ['Schema', 'The share of answers with the required structure.'],
        ['Latency p50 s', 'The typical answer time in seconds.'],
        ['Latency p95 s', 'The slow-case answer time: 95% were faster.'],
        ['Mean cost USD', 'The average model cost of 1 answer.'],
      ],
    },
  ],
  [
    'per question (answers)',
    {
      summary: 'The grades, time, and cost of each answer, 1 row per question.',
      terms: [
        QUESTION,
        TYPE,
        [
          'Outcome',
          '"answered", or "out_of_scope" when Keel declined the question.',
        ],
        [
          'Requests',
          'Model calls for this answer. Keel makes exactly 1 per answered question.',
        ],
        FAITHFULNESS,
        PRECISION,
        COVERAGE,
        ['Numeric', 'Whether the number matches the filing.'],
        [
          'Checks',
          'Extra checks for special questions: refusal ok or missed, adversarial ok or failed, and the number comparison.',
        ],
        ['Latency s', 'Answer time in seconds.'],
        ['Cost USD', 'Model cost of the answer.'],
        [
          'Output tokens',
          'How much text the model wrote, in tokens (about 3/4 of a word each).',
        ],
        ['Words', 'The length of the direct answer in words.'],
      ],
    },
  ],
  [
    'weakest answers',
    {
      summary:
        "The answers with the lowest faithfulness, worst first, with the judge's first objection.",
      terms: [
        QUESTION,
        FAITHFULNESS,
        PRECISION,
        [
          'First issue',
          'The first statement the judge marked as not fully supported (C1 is claim 1), and why.',
        ],
      ],
    },
  ],
];

/**
 * The note of a report section, by its heading.
 *
 * @param heading The section heading; null for the text before it.
 * @return The note, or null for a section without one.
 */
export function guideFor(heading: string | null): SectionGuide | null {
  const text = (heading ?? '').toLowerCase();
  if (text === '') {
    return null;
  }
  const found = GUIDES.find(([prefix]) => text.startsWith(prefix));
  return found?.[1] ?? null;
}
