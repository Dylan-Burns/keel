/**
 * Saves a file in the browser. The page fetches every file with the bearer
 * token, so a plain link cannot download it: the bytes go to a blob URL and
 * a temporary `<a download>` saves them.
 */
import type {MemoFormat} from '../api/admin';
import {fetchFile, memoPath} from '../api/admin';

/**
 * Saves a blob as a file through a temporary link.
 *
 * @param name The file name.
 * @param blob The content.
 */
export function saveBlob(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.rel = 'noopener';
  document.body.append(link);
  link.click();
  link.remove();
  // Revoke later: an immediate revoke can cancel the download in some browsers.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Fetches a file with the token and saves it.
 *
 * @param path The API path.
 * @param fallback The file name when the response names none.
 * @return The saved file name.
 */
export async function downloadFile(
  path: string,
  fallback: string,
): Promise<string> {
  const file = await fetchFile(path, fallback);
  saveBlob(file.name, file.blob);
  return file.name;
}

/**
 * Downloads the memo of a stored answer (chapter 27.2).
 *
 * @param requestId The request ID.
 * @param format `markdown` or `docx`.
 * @return The saved file name.
 */
export function downloadMemo(
  requestId: string,
  format: MemoFormat,
): Promise<string> {
  const extension = format === 'docx' ? 'docx' : 'md';
  return downloadFile(
    memoPath(requestId, format),
    `keel-memo-${requestId}.${extension}`,
  );
}
