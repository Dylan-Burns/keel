import type {JSX} from 'react';

import type {MemoFormat} from '../api/admin';

/** Props of Footer. */
export interface FooterProps {
  readonly requestId: string | null;
  readonly promptVersion: string | null;
  /** False when no answer exists yet: the footer then hides. */
  readonly hasAnswer: boolean;
  readonly copyStatus: string | null;
  readonly onCopy: () => void;
  readonly onExport: () => void;
  /** False until the final answer is stored, so the link can open it. */
  readonly canShare: boolean;
  /** Copies the shareable link `/a/{request_id}` (chapter 27.2). */
  readonly onShare: () => void;
  /** Downloads the memo of the stored answer (chapter 27.2). */
  readonly onMemo: (format: MemoFormat) => void;
}

/**
 * The footer (chapter 14.5): Copy as markdown, Export JSON, the memo
 * downloads (`keel export` as Markdown or DOCX), Copy link (the shareable
 * link of chapter 27.2), the request ID, and the prompt version. It shows
 * only once a question has an answer: before that, every button would be
 * off. The page links live in the top bar (`PageNav`).
 *
 * @param props The props.
 * @return The footer, or nothing before an answer.
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
  onMemo,
}: FooterProps): JSX.Element | null {
  if (!hasAnswer) {
    return null;
  }
  return (
    <footer className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-line bg-panel px-3 py-1.5 text-xs text-muted">
      <button type="button" className="btn" onClick={onCopy}>
        Copy as markdown
      </button>
      <button type="button" className="btn" onClick={onExport}>
        Export JSON
      </button>
      <button
        type="button"
        className="btn"
        data-testid="memo-markdown"
        disabled={!canShare}
        title="Download the memo as Markdown"
        onClick={() => onMemo('markdown')}
      >
        Memo .md
      </button>
      <button
        type="button"
        className="btn"
        data-testid="memo-docx"
        disabled={!canShare}
        title="Download the memo as a Word document"
        onClick={() => onMemo('docx')}
      >
        Memo .docx
      </button>
      <button
        type="button"
        className="btn"
        data-testid="share-link"
        disabled={!canShare}
        onClick={onShare}
      >
        Copy link
      </button>
      {copyStatus !== null && (
        <span className="font-mono text-[11px] text-up" role="status">
          {copyStatus}
        </span>
      )}
      <span className="num ml-auto text-[11px]" data-testid="request-id">
        {requestId === null ? '' : `request ${requestId}`}
      </span>
      <span className="num text-[11px]" data-testid="prompt-version">
        {promptVersion === null ? '' : `prompt ${promptVersion}`}
      </span>
    </footer>
  );
}
