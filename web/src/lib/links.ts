/**
 * The client routes of chapter 27.2: the shareable link of a stored answer
 * (`/a/{request_id}`), the history page (`/history`), and the re-run link
 * that opens the question page with a question to ask again.
 */

/** The query parameter of a question to ask again. */
export const RERUN_PARAM = 'rerun';

/** The path of the history page. */
export const HISTORY_PATH = '/history';

/** The client route of a stored answer: `/a/{request_id}`. */
export const SHARED_ROUTE = /^\/a\/([A-Za-z0-9._:-]{1,128})\/?$/;

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
 * The path that opens the question page and asks a question again.
 *
 * @param question The question.
 * @return `/?rerun=<question>`.
 */
export function rerunPath(question: string): string {
  return `/?${RERUN_PARAM}=${encodeURIComponent(question)}`;
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
 * The question to ask again from the page URL, when there is one.
 *
 * @param search The location query string.
 * @return The question, or null.
 */
export function rerunQuestion(search: string): string | null {
  const value = new URLSearchParams(search).get(RERUN_PARAM);
  return value === null || value.trim() === '' ? null : value;
}
