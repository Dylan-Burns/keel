import type {JSX} from 'react';

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

/** Props of PageNav. */
export interface PageNavProps {
  /**
   * True for an admin token: the jobs, users, and system links show. The
   * API refuses those routes to other roles; the links only follow it.
   */
  readonly isAdmin?: boolean;
  /**
   * True for a visitor of a public service (no token): the links of the
   * pages the API refuses to a visitor (403 `sign_in_required`) hide.
   */
  readonly isVisitor?: boolean;
}

/** A page link of the nav: its label, path, and test ID. */
interface PageLink {
  readonly label: string;
  readonly path: string;
  readonly testId: string;
  /** True when the page needs a token: a visitor does not see the link. */
  readonly needsToken?: boolean;
}

/** The pages every user can open. */
export const PAGE_LINKS: readonly PageLink[] = [
  {label: 'History', path: HISTORY_PATH, testId: 'history-link'},
  {label: 'Comp sets', path: COMPSETS_PATH, testId: 'compsets-link'},
  {label: 'Financials', path: FINANCIALS_PATH, testId: 'financials-link'},
  {
    label: 'Companies',
    path: COMPANIES_PATH,
    testId: 'companies-link',
    needsToken: true,
  },
  {label: 'Eval report', path: '/eval', testId: 'eval-link'},
  {label: 'Debug', path: DEBUG_PATH, testId: 'debug-link', needsToken: true},
  {label: 'Data use', path: HELP_PATH, testId: 'help-link'},
];

/** The pages only an admin can open. */
export const ADMIN_LINKS: readonly PageLink[] = [
  {label: 'Jobs', path: JOBS_PATH, testId: 'jobs-link'},
  {label: 'Users', path: USERS_PATH, testId: 'users-link'},
  {label: 'System', path: SYSTEM_PATH, testId: 'system-link'},
];

/**
 * The page links under the top bar: history, comp sets, financials,
 * companies, the eval report, debug, and the data use page
 * for every user, then the admin pages for an admin, set apart. A visitor
 * of a public service does not see the pages that need a token.
 *
 * @param props Whether the token is an admin token, or there is none.
 * @return The nav.
 */
export function PageNav({
  isAdmin = false,
  isVisitor = false,
}: PageNavProps): JSX.Element {
  const pages = isVisitor
    ? PAGE_LINKS.filter(link => link.needsToken !== true)
    : PAGE_LINKS;
  const groups = isAdmin ? [pages, ADMIN_LINKS] : [pages];
  return (
    <nav
      className="flex flex-wrap items-center gap-y-1 border-t border-line px-1.5 py-1"
      aria-label="Pages"
      data-testid="page-nav"
    >
      {groups.map((group, index) => (
        <span
          key={index === 0 ? 'pages' : 'admin'}
          className={`flex flex-wrap items-center divide-x divide-line ${
            index > 0 ? 'ml-2 rounded-sm bg-accent/10 py-0.5' : ''
          }`}
          data-testid={index === 0 ? 'page-links' : 'admin-links'}
        >
          {group.map(link => (
            <a
              key={link.testId}
              href={link.path}
              className={`px-2.5 font-mono text-[11px] uppercase leading-4 tracking-[0.08em] hover:text-accent hover:underline hover:underline-offset-4 ${
                index > 0 ? 'text-accent' : 'text-ink-2'
              }`}
              data-testid={link.testId}
            >
              {link.label}
            </a>
          ))}
        </span>
      ))}
    </nav>
  );
}
