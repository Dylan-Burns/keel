/**
 * The client of the admin, watch list, debug, and memo routes
 * (docs/API_ADMIN.md, chapter 27.2). Every call sends the bearer token; the
 * server enforces the admin role, so a page that hides a control never
 * replaces the check.
 */
import type {
  AuditList,
  BackupList,
  CostEstimate,
  CostQuery,
  DebugRetrieve,
  DebugUnderstand,
  DirectoryResponse,
  DirectorySearch,
  IndustryCompanies,
  Job,
  JobList,
  JobRequest,
  JobSubmitted,
  SystemResponse,
  UserCreated,
  UserList,
  WatchAdded,
  WatchList,
} from './types';
import {ApiError, authHeaders, getJson, sendJson, toApiError} from './client';

/**
 * Unwraps a JSON body that must be present.
 *
 * @param value The parsed body or null for HTTP 204.
 * @return The body.
 * @throws ApiError When the body is empty.
 */
function present<T>(value: T | null): T {
  if (value === null) {
    throw new ApiError(204, 'empty_body', 'The response is empty', null);
  }
  return value;
}

/**
 * `GET /api/admin/jobs?limit=1` as a role probe: HTTP 200 (or the 503 of a
 * job store that is down) means an admin token, 403 a token of another role.
 *
 * @return True for an admin.
 * @throws ApiError On 401 and on any other failure.
 */
export async function probeAdmin(): Promise<boolean> {
  try {
    await getJson<JobList>('/api/admin/jobs?limit=1');
    return true;
  } catch (error: unknown) {
    if (error instanceof ApiError && error.status === 403) {
      return false;
    }
    // Only the job store's own 503 proves the route let an admin in.
    if (
      error instanceof ApiError &&
      error.status === 503 &&
      (error.code === 'jobs_unavailable' || error.code === 'store_unavailable')
    ) {
      return true;
    }
    throw error;
  }
}

/**
 * `GET /api/admin/jobs`.
 *
 * @param limit The most jobs returned, 1 to 200.
 * @return The jobs, newest first, and the heavy job that holds the slot.
 */
export const fetchJobs = (limit = 50): Promise<JobList> =>
  getJson(`/api/admin/jobs?limit=${limit}`);

/**
 * `GET /api/admin/jobs/{id}`: 1 job with its log tail.
 *
 * @param id The job ID.
 * @return The job.
 */
export const fetchJob = (id: string): Promise<Job> =>
  getJson(`/api/admin/jobs/${encodeURIComponent(id)}`);

/**
 * `POST /api/admin/jobs`.
 *
 * @param request The kind, the parameters, and the typed confirmation.
 * @return The queued job, its warnings, and its cost estimate.
 * @throws ApiError With `detail.job_id` on 409 and `detail.confirm` on 400.
 */
export async function submitJob(request: JobRequest): Promise<JobSubmitted> {
  return present(
    await sendJson<JobSubmitted>('POST', '/api/admin/jobs', request),
  );
}

/**
 * `POST /api/admin/jobs/{id}/cancel`: only a queued job cancels.
 *
 * @param id The job ID.
 * @return The cancelled job.
 */
export async function cancelJob(id: string): Promise<Job> {
  return present(
    await sendJson<Job>(
      'POST',
      `/api/admin/jobs/${encodeURIComponent(id)}/cancel`,
    ),
  );
}

/**
 * The query string of a cost preview.
 *
 * @param query The job parameters.
 * @return The path with its query.
 */
export function costPath(query: CostQuery): string {
  const search = new URLSearchParams({kind: query.kind});
  if (query.kind === 'eval') {
    search.set('answers', String(query.answers));
    search.set('judge', String(query.judge));
    if (query.subset !== null && query.subset !== '') {
      search.set('subset', query.subset);
    }
  } else {
    search.set('refresh', String(query.refresh));
    search.set('facts_only', String(query.facts_only));
  }
  return `/api/admin/costs/preview?${search.toString()}`;
}

/**
 * `GET /api/admin/costs/preview`.
 *
 * @param query The job parameters.
 * @return The estimate with the confirmation the job needs.
 */
export const fetchCostPreview = (query: CostQuery): Promise<CostEstimate> =>
  getJson(costPath(query));

/** `GET /api/admin/users`. @return The users, without tokens. */
export const fetchUsers = (): Promise<UserList> => getJson('/api/admin/users');

/**
 * `POST /api/admin/users`: the only response that holds the new token.
 *
 * @param name The user name.
 * @param role The role.
 * @return The user with the token.
 */
export async function addUser(
  name: string,
  role: string,
): Promise<UserCreated> {
  return present(
    await sendJson<UserCreated>('POST', '/api/admin/users', {name, role}),
  );
}

/**
 * `DELETE /api/admin/users/{name}`.
 *
 * @param name The user name.
 * @return Resolves when the user is gone.
 */
export async function removeUser(name: string): Promise<void> {
  await sendJson('DELETE', `/api/admin/users/${encodeURIComponent(name)}`);
}

/** `GET /api/admin/system`. @return The system page data. */
export const fetchSystem = (): Promise<SystemResponse> =>
  getJson('/api/admin/system');

/** `GET /api/admin/backups`. @return The archives, newest first. */
export const fetchBackups = (): Promise<BackupList> =>
  getJson('/api/admin/backups');

/**
 * `GET /api/admin/audit`.
 *
 * @param limit The most rows, 1 to 500.
 * @return The admin audit, newest first.
 */
export const fetchAudit = (limit = 100): Promise<AuditList> =>
  getJson(`/api/admin/audit?limit=${limit}`);

/** `GET /api/watch`. @return The watch list. */
export const fetchWatch = (): Promise<WatchList> => getJson('/api/watch');

/**
 * `POST /api/watch` (admin).
 *
 * @param tickers The tickers to watch.
 * @return The added and the unchanged tickers.
 */
export async function addWatch(
  tickers: readonly string[],
): Promise<WatchAdded> {
  return present(await sendJson<WatchAdded>('POST', '/api/watch', {tickers}));
}

/**
 * `DELETE /api/watch/{ticker}` (admin).
 *
 * @param ticker The ticker.
 * @param user The user who watches it, or null for the caller.
 * @return Resolves when the row is gone.
 */
export async function removeWatch(
  ticker: string,
  user: string | null,
): Promise<void> {
  const query = user === null ? '' : `?user=${encodeURIComponent(user)}`;
  await sendJson('DELETE', `/api/watch/${encodeURIComponent(ticker)}${query}`);
}

/**
 * `POST /api/debug/understand`: the question analysis, no model request.
 *
 * @param question The question.
 * @return The analysis.
 */
export async function debugUnderstand(
  question: string,
): Promise<DebugUnderstand> {
  return present(
    await sendJson<DebugUnderstand>('POST', '/api/debug/understand', {
      question,
    }),
  );
}

/**
 * `POST /api/debug/retrieve`: the retrieval, no model request.
 *
 * @param question The question.
 * @return The retrieval summary.
 */
export async function debugRetrieve(question: string): Promise<DebugRetrieve> {
  return present(
    await sendJson<DebugRetrieve>('POST', '/api/debug/retrieve', {question}),
  );
}

/** A file the API returned: its bytes and its name. */
export interface FetchedFile {
  readonly blob: Blob;
  readonly name: string;
}

/**
 * The file name of a `Content-Disposition` header.
 *
 * @param header The header value or null.
 * @param fallback The name without a header.
 * @return The name, without any path.
 */
export function fileNameOf(header: string | null, fallback: string): string {
  const match = /(?:^|;)\s*filename="?([^";]+)"?/i.exec(header ?? '');
  const name = match?.[1]?.split(/[\\/]/).pop()?.trim() ?? '';
  return name === '' ? fallback : name;
}

/**
 * GETs a file with the bearer token.
 *
 * @param path The path under the same origin.
 * @param fallback The file name when the response names none.
 * @return The bytes and the name.
 * @throws ApiError On an HTTP error.
 */
export async function fetchFile(
  path: string,
  fallback: string,
): Promise<FetchedFile> {
  const response = await fetch(path, {headers: {...authHeaders()}});
  if (!response.ok) {
    throw await toApiError(response);
  }
  return {
    blob: await response.blob(),
    name: fileNameOf(response.headers.get('Content-Disposition'), fallback),
  };
}

/** The memo formats of `GET /api/export/{request_id}`. */
export type MemoFormat = 'markdown' | 'docx';

/**
 * The path of the memo of an answer.
 *
 * @param requestId The request ID.
 * @param format `markdown` or `docx`.
 * @return The export path.
 */
export function memoPath(requestId: string, format: MemoFormat): string {
  return `/api/export/${encodeURIComponent(requestId)}?format=${format}`;
}

/**
 * The path of a backup archive download.
 *
 * @param name The archive name from the listing.
 * @return The path.
 */
export function backupPath(name: string): string {
  return `/api/admin/backups/${encodeURIComponent(name)}`;
}

/**
 * `GET /api/admin/directory`: the sectors and their industries.
 *
 * @return The sectors, with the company count of each cached industry.
 */
export const fetchDirectory = (): Promise<DirectoryResponse> =>
  getJson('/api/admin/directory');

/**
 * `GET /api/admin/directory/sic/{code}`: the companies of 1 industry. The
 * first call of a code asks SEC EDGAR; later calls read the server cache.
 *
 * @param code The SIC code, 4 digits.
 * @return The companies with a ticker.
 */
export const fetchIndustry = (code: string): Promise<IndustryCompanies> =>
  getJson(`/api/admin/directory/sic/${encodeURIComponent(code)}`);

/**
 * `GET /api/admin/directory/search`: companies by ticker or name.
 *
 * @param query The text, 2 to 64 characters.
 * @param signal Aborts the request when the text changes.
 * @return At most 50 companies, best match first.
 */
export const searchDirectory = (
  query: string,
  signal?: AbortSignal,
): Promise<DirectorySearch> =>
  getJson(`/api/admin/directory/search?q=${encodeURIComponent(query)}`, signal);
