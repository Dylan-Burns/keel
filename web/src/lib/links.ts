/**
 * The client routes of chapter 27.2: the shareable link of a stored answer
 * (`/a/{request_id}`) and the history page (`/history`).
 */

/** The path of the history page. */
export const HISTORY_PATH = '/history';

/** The path of the comp sets page (chapter 27.2). */
export const COMPSETS_PATH = '/compsets';

/** The path of the data use page (chapter 27.2). */
export const HELP_PATH = '/help';

/** The path of the companies page: add, watch list, refresh, facts. */
export const COMPANIES_PATH = '/companies';

/** The path of the admin jobs page; `/jobs/{id}` opens 1 job. */
export const JOBS_PATH = '/jobs';

/** The path of the admin users page. */
export const USERS_PATH = '/users';

/** The path of the admin system page. */
export const SYSTEM_PATH = '/system';

/** The path of the debug page: understand and retrieve, no model call. */
export const DEBUG_PATH = '/debug';

/** The client route of 1 admin job: `/jobs/{id}` with a 16-hex ID. */
export const JOB_ROUTE = /^\/jobs\/([0-9a-f]{16})\/?$/;

/**
 * The path of 1 admin job.
 *
 * @param id The job ID.
 * @return `/jobs/{id}`.
 */
export function jobPath(id: string): string {
  return `${JOBS_PATH}/${encodeURIComponent(id)}`;
}

/**
 * The job ID of a `/jobs/{id}` path.
 *
 * @param pathname The location path.
 * @return The ID, or null on another path.
 */
export function jobIdOf(pathname: string): string | null {
  return JOB_ROUTE.exec(pathname)?.[1] ?? null;
}

/** The client route of a stored answer: `/a/{request_id}`. */
export const SHARED_ROUTE = /^\/a\/([A-Za-z0-9._:%-]{1,384})\/?$/;

/**
 * The path of the shareable link of an answer.
 *
 * @param requestId The request ID.
 * @return `/a/{request_id}`.
 */
export function sharePath(requestId: string): string {
  return `/a/${encodeURIComponent(requestId)}`;
}

/**
 * The full shareable link of an answer on this origin.
 *
 * @param requestId The request ID.
 * @param origin The page origin.
 * @return The absolute link.
 */
export function shareUrl(
  requestId: string,
  origin: string = window.location.origin,
): string {
  return `${origin}${sharePath(requestId)}`;
}

/**
 * The request ID of the shared answer route, when the path is one.
 *
 * @param pathname The location path.
 * @return The request ID, or null.
 */
export function sharedRequestId(pathname: string): string | null {
  const match = SHARED_ROUTE.exec(pathname);
  return match?.[1] === undefined ? null : decodeURIComponent(match[1]);
}

/**
 * Copies a text to the clipboard, or rejects where the page has no
 * clipboard (an insecure context), instead of throwing at once.
 *
 * @param text The text.
 * @return The write.
 */
export function copyText(text: string): Promise<void> {
  const clipboard = (navigator as {clipboard?: Clipboard}).clipboard;
  return clipboard === undefined
    ? Promise.reject(new Error('no clipboard in this context'))
    : clipboard.writeText(text);
}
