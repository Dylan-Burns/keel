import type {JSX} from 'react';

/** Props of Footer. */
export interface FooterProps {
  readonly requestId: string | null;
  readonly promptVersion: string | null;
  /** False when no answer exists yet. */
  readonly hasAnswer: boolean;
  readonly copyStatus: string | null;
  readonly onCopy: () => void;
  readonly onExport: () => void;
}

/**
 * The footer (chapter 14.5): Copy as markdown, Export JSON, the link to the
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
      {copyStatus !== null && <span role="status">{copyStatus}</span>}
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
