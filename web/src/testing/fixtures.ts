/**
 * Recorded API data for the Vitest tests and the Playwright route mocks. The
 * shapes follow chapter 14.2 and 14.3 and the mini corpus of the CI index
 * (AAPL, JPM, NVDA). The application code never imports this module.
 */
import type {
  AskResponse,
  CoverageResponse,
  EvalResponse,
  IndexStatusResponse,
  ReadyResponse,
  RetrievalSummary,
  SseEvent,
} from '../api/types';

/** Example question 1 (G-06). */
export const QUESTION_1 =
  'What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?';

/** Example question 2 (G-11). */
export const QUESTION_2 =
  "How has NVIDIA's revenue and growth outlook changed over the last two years?";

/** The ready body of a built index with a provider key. */
export const READY: ReadyResponse = {
  ready: true,
  index_version: '1.0.0',
  checks: {
    index_loaded: true,
    index_verified: true,
    models_loaded: true,
    provider_key: true,
  },
};

/** The ready body without an index (E-F-01). */
export const READY_NO_INDEX: ReadyResponse = {
  ready: false,
  index_version: null,
  checks: {index_loaded: false, provider_key: true},
};

/** The index status of a fresh index. */
export const INDEX_STATUS: IndexStatusResponse = {
  index_version: '1.0.0',
  corpus_checksum_match: true,
  warnings: [],
};

/** The index status after a corpus change (E-F-02). */
export const INDEX_STATUS_STALE: IndexStatusResponse = {
  index_version: '1.0.0',
  corpus_checksum_match: false,
  warnings: ['The corpus checksum differs from the build manifest.'],
};

/** The coverage of the mini corpus: 3 companies, 3 filings. */
export const COVERAGE: CoverageResponse = {
  companies: [
    {
      ticker: 'AAPL',
      company: 'Apple Inc.',
      forms: ['10-Q'],
      fiscal_periods: ['Q1 FY2023'],
    },
    {
      ticker: 'JPM',
      company: 'JPMorgan Chase & Co.',
      forms: ['10-K'],
      fiscal_periods: ['FY2025'],
    },
    {
      ticker: 'NVDA',
      company: 'NVIDIA Corporation',
      forms: ['10-K'],
      fiscal_periods: ['FY2025'],
    },
  ],
  filing_count: 3,
  quarantined: [],
};

const AAPL_CHUNK = 'AAPL_10Q_2022-12-31__risk_factors__0000';
const JPM_CHUNK = 'JPM_10K_2025-12-31__risk_factors__0003';
const NVDA_CHUNK = 'NVDA_10K_2025-01-26__mdna__0002';

/** The retrieval of example question 1 in the mini corpus. */
export const RETRIEVAL_1: RetrievalSummary = {
  chunks: [
    {
      chunk_id: JPM_CHUNK,
      ticker: 'JPM',
      form: '10-K',
      fiscal_label: 'FY2025',
      section: 'risk_factors',
      score: 0.91,
      filing_name: 'JPMorgan Chase & Co. 10-K FY2025',
      sec_url:
        'https://www.sec.gov/Archives/edgar/data/19617/000001961726000010/jpm-20251231.htm',
    },
    {
      chunk_id: AAPL_CHUNK,
      ticker: 'AAPL',
      form: '10-Q',
      fiscal_label: 'Q1 FY2023',
      section: 'risk_factors',
      score: 0.84,
      filing_name: 'Apple Inc. 10-Q Q1 FY2023',
      sec_url:
        'https://www.sec.gov/Archives/edgar/data/320193/000032019323000006/aapl-20221231.htm',
    },
  ],
  collapsed_near_duplicates: 2,
  dropped_candidates: 14,
  token_estimate: 2400,
};

/** The final answer of example question 1: TSLA is not in the mini corpus. */
export const RESPONSE_1: AskResponse = {
  request_id: 'req-example-1',
  analysis: {
    tickers: ['AAPL', 'TSLA', 'JPM'],
    primary_type: 'comparison',
    time_scope: {kind: 'none'},
    entities: [
      {ticker: 'AAPL', company: 'Apple Inc.', text: 'Apple', rule: 'alias'},
      {ticker: 'TSLA', company: 'Tesla, Inc.', text: 'Tesla', rule: 'alias'},
      {
        ticker: 'JPM',
        company: 'JPMorgan Chase & Co.',
        text: 'JPMorgan',
        rule: 'alias',
      },
    ],
  },
  retrieval: RETRIEVAL_1,
  answer: {
    direct_answer:
      'Apple names supply chain and **foreign exchange** risk, while JPMorgan names credit and market risk. ' +
      'The corpus has no Tesla filing, so the comparison covers 2 of the 3 companies.',
    company_findings: [
      {
        ticker: 'AAPL',
        company: 'Apple Inc.',
        findings: [
          {
            point: 'Supply chain concentration in Asia.',
            citations: [AAPL_CHUNK],
          },
        ],
      },
      {
        ticker: 'JPM',
        company: 'JPMorgan Chase & Co.',
        findings: [
          {point: 'Credit losses in a downturn.', citations: [JPM_CHUNK]},
          {
            point: 'Liquidity stress in markets.',
            citations: [],
            unverified: true,
          },
        ],
      },
    ],
    comparison_table: {
      columns: ['Company', 'Main risk'],
      rows: [
        ['AAPL', 'Supply chain'],
        ['JPM', 'Credit'],
      ],
    },
    citations: [
      {
        chunk_id: AAPL_CHUNK,
        claim: 'Supply chain concentration',
        quote: 'The Company depends on component suppliers in Asia.',
      },
      {
        chunk_id: JPM_CHUNK,
        claim: 'Credit losses',
        quote: 'JPMorganChase could incur credit losses in a downturn.',
      },
    ],
    coverage: {
      companies_used: [
        {ticker: 'AAPL', forms: ['10-Q'], fiscal_periods: ['Q1 FY2023']},
        {ticker: 'JPM', forms: ['10-K'], fiscal_periods: ['FY2025']},
      ],
      companies_missing: ['TSLA'],
      data_as_of: '2026-02-13',
    },
    gaps: ['No Tesla filing is in the corpus.'],
    confidence: 'medium',
    confidence_reason: '2 of 3 companies covered.',
    next_questions: ['How did JPMorgan describe credit risk in FY2025?'],
    refusal: null,
  },
  citations_resolved: [
    {
      chunk_id: AAPL_CHUNK,
      filing_name: 'Apple Inc. 10-Q Q1 FY2023',
      section_title: 'Risk Factors',
      fiscal_label: 'Q1 FY2023',
      sec_url:
        'https://www.sec.gov/Archives/edgar/data/320193/000032019323000006/aapl-20221231.htm',
      valid: true,
    },
    {
      chunk_id: JPM_CHUNK,
      filing_name: 'JPMorgan Chase & Co. 10-K FY2025',
      section_title: 'Risk Factors',
      fiscal_label: 'FY2025',
      sec_url:
        'https://www.sec.gov/Archives/edgar/data/19617/000001961726000010/jpm-20251231.htm',
      valid: true,
    },
  ],
  meta: {
    model: 'mock',
    prompt_version: '1.0.0',
    index_version: '1.0.0',
    prompt_hash: 'sha256:0000',
    latency_ms: {
      understanding: 4,
      retrieval: 120,
      rerank: 300,
      first_token: 500,
      total: 1840,
    },
    usage: {input_tokens: 2400, cached_input_tokens: 0, output_tokens: 320},
    cost_usd: 0.012,
    degraded: false,
    from_cache: false,
    flags: {citation_drift: 0, injection_suspect: false},
  },
  audit: {
    request_id: 'req-example-1',
    tickers: ['AAPL', 'TSLA', 'JPM'],
    question_type: 'comparison',
    time_scope: 'none',
    filters: [
      {
        label: 'AAPL risk',
        tickers: ['AAPL'],
        sections: ['risk_factors'],
        filings: 0,
        windows: [],
      },
      {
        label: 'JPM risk',
        tickers: ['JPM'],
        sections: ['risk_factors'],
        filings: 1,
        windows: [['JPM', '2025-01-01', '2025-12-31']],
      },
    ],
    candidates: {
      gathered: 18,
      collapsed: 2,
      reranked: 16,
      per_company: [
        {ticker: 'AAPL', before: 8, after: 7},
        {ticker: 'JPM', before: 10, after: 9},
      ],
    },
    quota_fills: [
      {label: 'AAPL', taken: 16, quota: 16, candidates: 7, tokens: 1200},
      {label: 'JPM', taken: 11, quota: 16, candidates: 9, tokens: 1200},
    ],
    chunk_count: 2,
    token_estimate: 2400,
    prompt_hash: 'sha256:0000',
    prompt_version: '1.0.0',
    index_version: '1.0.0',
    model: 'mock',
    model_requests: 1,
    failed_before_content: 0,
    usage: {input_tokens: 2400, cached_input_tokens: 0, output_tokens: 320},
    cost_usd: 0.012,
    latency_ms: {first_token: 500, total: 1840},
    citation_drift: 0,
    unverified: 0,
    flags: {from_cache: false, degraded: false},
    outcome: 'answered',
    error: null,
  },
};

/** The final answer of example question 2: full coverage. */
export const RESPONSE_2: AskResponse = {
  ...RESPONSE_1,
  request_id: 'req-example-2',
  analysis: {
    tickers: ['NVDA'],
    primary_type: 'trend',
    time_scope: {kind: 'relative'},
  },
  retrieval: {
    chunks: [
      {
        chunk_id: NVDA_CHUNK,
        ticker: 'NVDA',
        form: '10-K',
        fiscal_label: 'FY2025',
        section: 'mdna',
        score: 0.88,
        filing_name: 'NVIDIA Corporation 10-K FY2025',
        sec_url:
          'https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm',
      },
    ],
    collapsed_near_duplicates: 0,
    dropped_candidates: 6,
    token_estimate: 1200,
  },
  answer: {
    direct_answer: 'NVIDIA revenue grew to $130.5 billion in FY2025, up 114%.',
    company_findings: [
      {
        ticker: 'NVDA',
        company: 'NVIDIA Corporation',
        findings: [
          {point: 'Revenue rose 114% in FY2025.', citations: [NVDA_CHUNK]},
        ],
      },
    ],
    comparison_table: null,
    citations: [
      {
        chunk_id: NVDA_CHUNK,
        claim: 'Revenue growth',
        quote: 'Revenue for fiscal year 2025 was $130.5 billion, up 114%.',
      },
    ],
    coverage: {
      companies_used: [
        {ticker: 'NVDA', forms: ['10-K'], fiscal_periods: ['FY2025']},
      ],
      companies_missing: [],
      data_as_of: '2025-02-26',
    },
    gaps: [],
    confidence: 'high',
    confidence_reason: 'The 10-K covers the question.',
    next_questions: [],
    refusal: null,
  },
  citations_resolved: [
    {
      chunk_id: NVDA_CHUNK,
      filing_name: 'NVIDIA Corporation 10-K FY2025',
      section_title: "Management's Discussion and Analysis",
      fiscal_label: 'FY2025',
      sec_url:
        'https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm',
      valid: true,
    },
  ],
};

/** The no-call response of an out-of-scope question. */
export const RESPONSE_OUT_OF_SCOPE: AskResponse = {
  ...RESPONSE_1,
  request_id: 'req-out-of-scope',
  analysis: {
    tickers: [],
    primary_type: 'out_of_scope',
    time_scope: {kind: 'none'},
  },
  retrieval: {
    chunks: [],
    collapsed_near_duplicates: 0,
    dropped_candidates: 0,
    token_estimate: 0,
  },
  answer: {
    ...RESPONSE_1.answer,
    direct_answer: '',
    company_findings: [],
    comparison_table: null,
    citations: [],
    coverage: {companies_used: [], companies_missing: [], data_as_of: ''},
    gaps: [],
    next_questions: [],
    refusal: {
      reason: 'Keel answers from SEC filings and does not predict prices.',
    },
  },
  citations_resolved: [],
  meta: {...RESPONSE_1.meta, cost_usd: 0, latency_ms: {total: 5}},
};

/**
 * The event sequence of 1 answer, split into deltas like a real stream.
 *
 * @param response The final response.
 * @param pieces How many `answer_delta` events to split the answer into.
 * @return The events from `meta` to `done`.
 */
export function eventsFor(response: AskResponse, pieces = 4): SseEvent[] {
  const text = response.answer.direct_answer;
  const size = Math.max(1, Math.ceil(text.length / pieces));
  const deltas: SseEvent[] = [];
  for (let start = 0; start < text.length; start += size) {
    deltas.push({
      event: 'answer_delta',
      data: {text: text.slice(start, start + size)},
    });
  }
  return [
    {
      event: 'meta',
      data: {
        request_id: response.request_id,
        index_version: response.meta.index_version,
        prompt_version: response.meta.prompt_version,
        model: response.meta.model,
      },
    },
    {event: 'analysis', data: response.analysis},
    ...(response.answer.refusal === null
      ? [{event: 'retrieval', data: response.retrieval} as SseEvent]
      : []),
    ...deltas,
    ...response.answer.company_findings.map(
      company => ({event: 'findings', data: company}) as SseEvent,
    ),
    {event: 'final', data: response},
    {event: 'done', data: null},
  ];
}

/**
 * Serializes events as the server writes them: `event:` and `data:` lines,
 * a blank line after each event, and a keep-alive comment first.
 *
 * @param events The events.
 * @return The SSE text.
 */
export function toSseText(events: readonly SseEvent[]): string {
  const blocks = events.map(
    e =>
      `event: ${e.event}\ndata: ${e.data === null ? '' : JSON.stringify(e.data)}\n\n`,
  );
  return `: ping\n\n${blocks.join('')}`;
}

/** The eval page data: a report with 3 gates and a prompt log (W-02). */
export const EVAL_PAGE: EvalResponse = {
  report: {
    source: 'eval/report.md',
    markdown:
      '# Eval report\n\nWritten by `keel eval`.\n\n## Regression gates\n\n' +
      '| Gate | Threshold | Value |\n| --- | --- | --- |\n' +
      '| Recall at 25 | >= 0.85 | 0.63 |\n\n' +
      '## Notes\n\nA <script>window.keelPwned = true</script> stays text.\n',
    truncated: false,
  },
  prompt_log: {
    source: 'docs/PROMPT_LOG.md',
    markdown:
      '# Prompt log\n\n| Version | Result |\n| --- | --- |\n| 1.3.0 | 0 flags |\n',
    truncated: false,
  },
  gates: [
    {
      name: 'Recall at 25',
      comparator: '>=',
      threshold: 0.85,
      threshold_text: '>= 0.85',
      value: 0.63,
      value_text: '0.63',
      status: 'fail',
      passed: false,
    },
    {
      name: 'MRR',
      comparator: '>=',
      threshold: 0.6,
      threshold_text: '>= 0.60',
      value: 0.88,
      value_text: '0.88',
      status: 'pass',
      passed: true,
    },
    {
      name: 'Faithfulness',
      comparator: '>=',
      threshold: 0.9,
      threshold_text: '>= 0.90',
      value: null,
      value_text: 'n/a',
      status: 'pending',
      passed: null,
    },
  ],
};

/** The eval page data before `keel eval` ran: no report, no gates. */
export const EVAL_PAGE_EMPTY: EvalResponse = {
  ...EVAL_PAGE,
  report: {source: 'eval/report.md', markdown: null, truncated: false},
  gates: [],
};
