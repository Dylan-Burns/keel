import {fireEvent, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../../api/client';
import {FORBIDDEN, routeFetch} from '../../testing/admin';
import {DebugPage} from './DebugPage';

const QUESTION = 'What are the risk factors facing Apple?';

const UNDERSTAND = {
  question: QUESTION,
  tickers: ['AAPL'],
  entities: [
    {
      ticker: 'AAPL',
      company: 'Apple Inc.',
      text: 'Apple',
      rule: 'capitalized',
      fuzzy: false,
      score: null,
    },
  ],
  groups: [],
  unknown_entities: [],
  not_indexed: [],
  time_scope: {
    kind: 'none',
    scopes: [],
    fiscal_year: null,
    fiscal_period: null,
  },
  primary_type: 'single_company',
  types: ['single_company'],
  topic_terms: ['risk factors'],
  section_weights: {risk_factors: 1.5},
  flags: {fuzzy: false, injection_suspect: false},
  out_of_scope_reason: null,
  suggested_tickers: [],
  elapsed_ms: 0.6,
  comp_sets: [],
};

const RETRIEVE = {
  question: QUESTION,
  primary_type: 'single_company',
  types: ['single_company'],
  tickers: ['AAPL'],
  out_of_scope: false,
  out_of_scope_reason: null,
  retrieval: {
    sub_queries: [
      {label: 'AAPL', dense_text: 'Apple Inc: risks', terms: ['risk factors']},
    ],
    candidates: 18,
    collapsed: 0,
    after_collapse: 18,
    reranked: 18,
    fills: [{label: 'AAPL', taken: 2, quota: 48, candidates: 18, tokens: 700}],
    context: {
      chunks: 2,
      token_estimate: 700,
      max_tokens: 32000,
      max_chunks: 48,
      dropped: 0,
      items: [
        {
          chunk_id: 'AAPL_10Q_2022-12-31__risk_factors__0000',
          ticker: 'AAPL',
          form: '10-Q',
          section: 'risk_factors',
          period_end_date: '2022-12-31',
          estimated_tokens: 330,
          truncated: false,
          score: 1.35,
        },
        {
          chunk_id: 'AAPL_10Q_2022-12-31__mdna__0000',
          ticker: 'AAPL',
          form: '10-Q',
          section: 'mdna',
          period_end_date: '2022-12-31',
          estimated_tokens: 370,
          truncated: true,
          score: 0.27,
        },
      ],
    },
    sections: {risk_factors: 1, mdna: 1},
    timings_ms: {lexical: 1, dense: 900, rerank: 880, total: 1800},
    gaps: [],
    degraded: [],
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('DebugPage', () => {
  it('runs understand and retrieve for an analyst with 0 model requests', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    const calls = routeFetch({
      'GET /api/admin/jobs': FORBIDDEN,
      'POST /api/debug/understand': {body: UNDERSTAND},
      'POST /api/debug/retrieve': {body: RETRIEVE},
    });
    render(<DebugPage />);
    expect(await screen.findByTestId('debug-requests')).toHaveTextContent(
      'model requests: 0',
    );
    fireEvent.change(screen.getByTestId('debug-question'), {
      target: {value: QUESTION},
    });
    fireEvent.click(screen.getByTestId('debug-run'));
    const chunks = await screen.findAllByTestId('debug-chunk');
    expect(chunks).toHaveLength(2);
    expect(chunks[0]).toHaveTextContent('1.35');
    expect(chunks[1]).toHaveTextContent('370 tok, cut');
    expect(screen.getByTestId('debug-entities')).toHaveTextContent(
      'Apple Inc.',
    );
    expect(screen.getByTestId('debug-plan')).toHaveTextContent(
      'risk_factors 1.5',
    );
    expect(screen.getByTestId('debug-counts')).toHaveTextContent(
      '2 of 48 from 18 candidates',
    );
    const posts = calls.filter(c => c.method === 'POST');
    expect(posts.map(c => [c.path, c.body])).toEqual([
      ['/api/debug/understand', {question: QUESTION}],
      ['/api/debug/retrieve', {question: QUESTION}],
    ]);
  });

  it('shows an out-of-scope question without chunks', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    routeFetch({
      'GET /api/admin/jobs': FORBIDDEN,
      'POST /api/debug/understand': {
        body: {...UNDERSTAND, out_of_scope_reason: 'not a filing question'},
      },
      'POST /api/debug/retrieve': {
        body: {
          ...RETRIEVE,
          out_of_scope: true,
          out_of_scope_reason: 'not a filing question',
          retrieval: null,
        },
      },
    });
    render(<DebugPage />);
    fireEvent.change(await screen.findByTestId('debug-question'), {
      target: {value: 'What is the weather?'},
    });
    fireEvent.click(screen.getByTestId('debug-run'));
    expect(await screen.findByTestId('debug-out-of-scope')).toHaveTextContent(
      'not a filing question',
    );
  });

  it('reports the rate limit', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    routeFetch({
      'GET /api/admin/jobs': FORBIDDEN,
      'POST /api/debug/understand': {
        status: 429,
        body: {detail: {code: 'rate_limited', message: 'slow', retry_after: 7}},
      },
      'POST /api/debug/retrieve': {body: RETRIEVE},
    });
    render(<DebugPage />);
    fireEvent.change(await screen.findByTestId('debug-question'), {
      target: {value: QUESTION},
    });
    fireEvent.click(screen.getByTestId('debug-run'));
    expect(await screen.findByTestId('debug-error')).toHaveTextContent(
      'try again in 7 seconds',
    );
  });
});
