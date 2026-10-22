import type {JSX} from 'react';

import {HISTORY_PATH} from '../lib/links';

/** Props of Footer. */
export interface FooterProps {
  readonly requestId: string | null;
  readonly promptVersion: string | null;
  /** False when no answer exists yet. */
  readonly hasAnswer: boolean;
  readonly copyStatus: string | null;
  readonly onCopy: () => void;
  readonly onExport: () => void;
  /** False until the final answer is stored, so the link can open it. */
  readonly canShare: boolean;
  /** Copies the shareable link `/a/{request_id}` (chapter 27.2). */
  readonly onShare: () => void;
}

/**
 * The footer (chapter 14.5): Copy as markdown, Export JSON, Copy link (the
 * shareable link of chapter 27.2), the links to the history page and the
 * eval page (W-02), the request ID, and the prompt version.
 *
 * @param props The props.
 * @return The footer.
 */
export function Footer({
  requestId,
  promptVersion,
  hasAnswer,
  copyStatus,
  onCopy,
  onExport,
  canShare,
  onShare,
}: FooterProps): JSX.Element {
  return (
    <footer className="flex flex-wrap items-center gap-3 border-t border-slate-200 bg-white px-4 py-2 text-xs text-slate-600">
      <button
        type="button"
        className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50"
        disabled={!hasAnswer}
        onClick={onCopy}
      >
        Copy as markdown
      </button>
      <button
        type="button"
        className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50"
        disabled={!hasAnswer}
        onClick={onExport}
      >
        Export JSON
      </button>
      <button
        type="button"
        className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50"
        data-testid="share-link"
        disabled={!canShare}
        onClick={onShare}
      >
        Copy link
      </button>
      {copyStatus !== null && <span role="status">{copyStatus}</span>}
      <button
        type="button"
        className="underline"
        data-testid="history-link"
        onClick={() => window.location.assign(HISTORY_PATH)}
      >
        History
      </button>
      <button
        type="button"
        className="underline"
        data-testid="eval-link"
        onClick={() => window.location.assign('/eval')}
      >
        Eval report
      </button>
      <span className="ml-auto font-mono" data-testid="request-id">
        {requestId === null ? '' : `request ${requestId}`}
      </span>
      <span data-testid="prompt-version">
        {promptVersion === null ? '' : `prompt ${promptVersion}`}
      </span>
    </footer>
  );
}
