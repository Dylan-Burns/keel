/**
 * Fixtures and a routed fetch stub for the operations page tests. The
 * bodies follow docs/API_ADMIN.md.
 */
import {vi} from 'vitest';

import type {
  BackupList,
  CostEstimate,
  Job,
  JobStep,
  SystemResponse,
} from '../api/types';

/** A recorded call of the stub: method, path, and parsed JSON body. */
export interface Call {
  readonly method: string;
  readonly path: string;
  readonly body: unknown;
}

/** A reply: a status and a JSON body, or a function of the call. */
export type Reply =
  | {readonly status?: number; readonly body?: unknown}
  | ((call: Call) => {readonly status?: number; readonly body?: unknown});

/**
 * Stubs `fetch` with routes keyed `METHOD /path?query`, falling back to the
 * key without the query. An unknown route answers 404.
 *
 * @param routes The replies.
 * @return The calls, in order.
 */
export function routeFetch(routes: Record<string, Reply>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      const body: unknown =
        typeof init?.body === 'string' ? JSON.parse(init.body) : null;
      const call = {method, path, body};
      calls.push(call);
      const bare = path.split('?')[0] ?? path;
      const reply = routes[`${method} ${path}`] ?? routes[`${method} ${bare}`];
      const resolved =
        reply === undefined
          ? {
              status: 404,
              body: {detail: {code: 'not_found', message: 'no route'}},
            }
          : typeof reply === 'function'
            ? reply(call)
            : reply;
      const status = resolved.status ?? 200;
      return Promise.resolve(
        status === 204
          ? new Response(null, {status})
          : new Response(JSON.stringify(resolved.body ?? {}), {status}),
      );
    }),
  );
  return calls;
}

/** The 403 body of an admin route for another role. */
export const FORBIDDEN = {
  status: 403,
  body: {detail: {code: 'forbidden', message: 'the route is for admins'}},
};

/**
 * A job record.
 *
 * @param fields The fields to change.
 * @return The job.
 */
export function job(fields: Partial<Job> = {}): Job {
  return {
    id: '3f2a9c0d1e4b5a67',
    kind: 'add',
    params: {ticker: 'ZTS'},
    requested_by: 'carol',
    heavy: true,
    status: 'queued',
    progress: {done: 0, total: null},
    phase: 'queued',
    created_at: '2026-10-22T18:00:00+00:00',
    started_at: null,
    finished_at: null,
    result: null,
    error: null,
    log: [],
    ...fields,
  };
}

/**
 * A job step.
 *
 * @param fields The fields to change.
 * @return The step.
 */
export function jobStep(fields: Partial<JobStep> = {}): JobStep {
  return {
    key: 'parse',
    name: 'Parse and section',
    status: 'pending',
    started_at: null,
    finished_at: null,
    progress: null,
    log: [],
    ...fields,
  };
}

/** The 202 body of a submitted job. */
export function submitted(fields: Partial<Job> = {}): unknown {
  return {job: job(fields), warnings: [], estimate: null};
}

/** A cost estimate of an eval with answers. */
export const ESTIMATE: CostEstimate = {
  kind: 'eval',
  questions: 24,
  model_requests: 24,
  judge_requests: 24,
  answer_usd: 0.0936,
  judge_usd: 0.084,
  usd: 4.26,
  basis: 'audit',
  confirm: 'cost',
};

/** The backup listing. */
export const BACKUPS: BackupList = {
  directory: 'backups',
  items: [
    {
      name: 'keel-2026-10-22T023000Z.tar.gz',
      size_bytes: 123456,
      created_at: '2026-10-22T02:30:00+00:00',
      sha256: 'a'.repeat(64),
    },
  ],
};

/** The system page data. */
export const SYSTEM: SystemResponse = {
  version: '0.2.0',
  offline: false,
  provider: 'mock',
  model: 'claude-sonnet-5-5',
  doctor: [
    {name: 'python', status: 'ok', detail: '3.12.13'},
    {name: 'ANTHROPIC_API_KEY', status: 'warn', detail: 'absent'},
  ],
  doctor_failed: false,
  inventory: {
    file_count: 3,
    total_bytes: 68841,
    ticker_count: 3,
    form_counts: {'10-K': 2, '10-Q': 1},
    first_filing: '2023-02-03',
    last_filing: '2026-02-13',
    manifest_present: false,
    discrepancy_count: 0,
    discrepancies: [],
  },
  index: {
    loaded: true,
    index_version: '1.0.0',
    build_id: '20261022T194126317602Z',
    verified: true,
    error: null,
    corpus_checksum_match: true,
    corpus_note: null,
    built_at: '2026-10-22T19:42:57Z',
    counts: {chunks: 110, table_chunks: 36},
    filings: 3,
    quarantined: 0,
  },
  backups: BACKUPS,
  scheduler: {
    enabled: false,
    running: false,
    refresh_at: '02:00',
    backup_at: '02:30',
    backup_keep: 7,
    backup_bucket_set: false,
    jobs: [],
  },
  budget: {daily_usd: 20, spent_usd: 0, stopped: false},
  active_job: null,
  bootstrap: null,
};
