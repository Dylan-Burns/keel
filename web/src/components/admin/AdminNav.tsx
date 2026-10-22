import type {JSX} from 'react';

import {
  COMPANIES_PATH,
  DEBUG_PATH,
  JOBS_PATH,
  SYSTEM_PATH,
  USERS_PATH,
} from '../../lib/links';

/** The pages of the operations area. */
export type OpsPage = 'companies' | 'jobs' | 'users' | 'system' | 'debug';

/** 1 link of the operations navigation. */
interface OpsLink {
  readonly page: OpsPage;
  readonly label: string;
  readonly path: string;
  /** True for a page that only an admin can use. */
  readonly adminOnly: boolean;
}

/** The operations pages in navigation order. */
export const OPS_LINKS: readonly OpsLink[] = [
  {
    page: 'companies',
    label: 'Companies',
    path: COMPANIES_PATH,
    adminOnly: false,
  },
  {page: 'jobs', label: 'Jobs', path: JOBS_PATH, adminOnly: true},
  {page: 'users', label: 'Users', path: USERS_PATH, adminOnly: true},
  {page: 'system', label: 'System', path: SYSTEM_PATH, adminOnly: true},
  {page: 'debug', label: 'Debug', path: DEBUG_PATH, adminOnly: false},
];

/** Props of AdminNav. */
export interface AdminNavProps {
  /** The page shown now. */
  readonly current: OpsPage;
  /** True for an admin: the admin pages join the links. */
  readonly isAdmin: boolean;
}

/**
 * The tab strip of the operations pages. An admin sees every page; an
 * analyst or a partner sees the pages open to every role. Hiding a link is
 * a convenience: the API refuses the admin routes to other roles.
 *
 * @param props The props.
 * @return The navigation.
 */
export function AdminNav({current, isAdmin}: AdminNavProps): JSX.Element {
  const links = OPS_LINKS.filter(link => isAdmin || !link.adminOnly);
  return (
    <nav
      className="border-b border-line bg-head"
      aria-label="Operations"
      data-testid="ops-nav"
    >
      <ul className="mx-auto flex w-full max-w-6xl overflow-x-auto px-3">
        {links.map(link => (
          <li key={link.page}>
            <a
              href={link.path}
              aria-current={link.page === current ? 'page' : undefined}
              data-testid={`ops-link-${link.page}`}
              className={`-mb-px inline-flex min-h-9 items-center border-b-2 px-3 font-mono text-[11px] uppercase tracking-[0.1em] ${
                link.page === current
                  ? 'border-accent text-ink'
                  : 'border-transparent text-muted hover:text-accent'
              }`}
            >
              {link.label}
              {link.adminOnly && <span className="sr-only"> (admin)</span>}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
