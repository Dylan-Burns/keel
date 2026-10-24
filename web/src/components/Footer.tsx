import type {JSX} from 'react';

import type {MemoFormat} from '../api/admin';
import {
  COMPANIES_PATH,
  COMPSETS_PATH,
  DEBUG_PATH,
  FINANCIALS_PATH,
  HELP_PATH,
  HISTORY_PATH,
  JOBS_PATH,
  SYSTEM_PATH,
  USERS_PATH,
} from '../lib/links';

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
  /** Downloads the memo of the stored answer (chapter 27.2). */
  readonly onMemo: (format: MemoFormat) => void;
  /**
   * True for an admin token: the jobs, users, and system links show. The
   * API refuses those routes to other roles; the links only follow it.
   */
  readonly isAdmin?: boolean;
}

/** A page link of the footer: its label, path, and test ID. */
interface PageLink {
  readonly label: string;
  readonly path: string;
  readonly testId: string;
  readonly adminOnly: boolean;
}

const PAGE_LINKS: readonly PageLink[] = [
  {
    label: 'History',
    path: HISTORY_PATH,
    testId: 'history-link',
    adminOnly: false,
  },
  {
    label: 'Comp sets',
    path: COMPSETS_PATH,
    testId: 'compsets-link',
    adminOnly: false,
  },
  {label: 'Eval report', path: '/eval', testId: 'eval-link', adminOnly: false},
  {
    label: 'Financials',
    path: FINANCIALS_PATH,
    testId: 'financials-link',
    adminOnly: false,
  },
  {
    label: 'Companies',
    path: COMPANIES_PATH,
    testId: 'companies-link',
    adminOnly: false,
  },
  {label: 'Debug', path: DEBUG_PATH, testId: 'debug-link', adminOnly: false},
  {label: 'Jobs', path: JOBS_PATH, testId: 'jobs-link', adminOnly: true},
  {label: 'Users', path: USERS_PATH, testId: 'users-link', adminOnly: true},
  {label: 'System', path: SYSTEM_PATH, testId: 'system-link', adminOnly: true},
  {label: 'Data use', path: HELP_PATH, testId: 'help-link', adminOnly: false},
];

/**
 * The footer (chapter 14.5): Copy as markdown, Export JSON, the memo
 * downloads (`keel export` as Markdown or DOCX), Copy link (the shareable
 * link of chapter 27.2), the links to the history page, the comp sets
 * page, the eval page (W-02), the companies and debug pages, the admin
 * pages for an admin, and the data use page (27.2), the request ID, and
 * the prompt version.
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
  onMemo,
  isAdmin = false,
}: FooterProps): JSX.Element {
  return (
    <footer className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-line bg-panel px-3 py-1.5 text-xs text-muted">
      <button
        type="button"
        className="btn"
        disabled={!hasAnswer}
        onClick={onCopy}
      >
        Copy as markdown
      </button>
      <button
        type="button"
        className="btn"
        disabled={!hasAnswer}
        onClick={onExport}
      >
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
      <nav
        className="flex flex-wrap items-center gap-3 sm:border-l sm:border-line sm:pl-3"
        aria-label="Pages"
      >
        {PAGE_LINKS.filter(link => isAdmin || !link.adminOnly).map(link => (
          <button
            key={link.testId}
            type="button"
            className={`font-mono text-[11px] uppercase tracking-[0.08em] hover:text-accent ${
              link.adminOnly ? 'text-accent' : 'text-ink-2'
            }`}
            data-testid={link.testId}
            onClick={() => window.location.assign(link.path)}
          >
            {link.label}
          </button>
        ))}
      </nav>
      <span className="num ml-auto text-[11px]" data-testid="request-id">
        {requestId === null ? '' : `request ${requestId}`}
      </span>
      <span className="num text-[11px]" data-testid="prompt-version">
        {promptVersion === null ? '' : `prompt ${promptVersion}`}
      </span>
    </footer>
  );
}
