import type {JSX, ReactNode} from 'react';
import {useState} from 'react';

import {setToken} from '../../api/client';
import {useAdminRole} from '../../useAdminRole';
import {PageBar} from '../PageBar';
import {TokenField} from '../TokenField';
import type {OpsPage} from './AdminNav';
import {AdminNav} from './AdminNav';

/** Props of AdminShell. */
export interface AdminShellProps {
  /** The page title, the h1. */
  readonly title: string;
  /** The page, for the navigation. */
  readonly current: OpsPage;
  /** True for a page that only an admin can use. */
  readonly adminOnly: boolean;
  /** The `data-testid` of the page root. */
  readonly testId: string;
  /**
   * The page body once the role is known.
   *
   * @param isAdmin True for an admin token.
   * @return The body.
   */
  readonly children: (isAdmin: boolean) => ReactNode;
}

/**
 * The frame of an operations page: the top bar with the token field, the
 * operations navigation, and the role gate. The body renders only when the
 * token passes; an admin-only page tells any other role that the API
 * refuses it. The API checks the role on every call, so the gate is a
 * convenience, not the control.
 *
 * @param props The props.
 * @return The page.
 */
export function AdminShell({
  title,
  current,
  adminOnly,
  testId,
  children,
}: AdminShellProps): JSX.Element {
  const [version, setVersion] = useState(0);
  const role = useAdminRole(version);
  const isAdmin = role.kind === 'admin';
  const known = role.kind === 'admin' || role.kind === 'member';
  const onSave = (token: string): void => {
    setToken(token);
    setVersion(n => n + 1);
  };
  return (
    <div
      className="min-h-screen bg-canvas font-sans text-ink"
      data-testid={testId}
      data-role={role.kind}
    >
      <PageBar title={title}>
        <TokenField
          hasToken={role.kind !== 'no_token'}
          rejected={role.kind === 'rejected'}
          onSave={onSave}
        />
      </PageBar>
      {known && <AdminNav current={current} isAdmin={isAdmin} />}
      <main className="mx-auto w-full max-w-6xl space-y-3 px-3 py-3">
        {role.kind === 'no_token' && (
          <p className="text-[13px] text-muted">
            Enter your access token to open this page.
          </p>
        )}
        {role.kind === 'rejected' && (
          <p className="notice notice-down text-[13px]" role="alert">
            The token was rejected. Enter it again.
          </p>
        )}
        {role.kind === 'loading' && (
          <p className="text-[13px] text-muted">Checking your role.</p>
        )}
        {role.kind === 'error' && (
          <p className="notice notice-down text-[13px]" role="alert">
            {role.message}
          </p>
        )}
        {role.kind === 'member' && adminOnly && (
          <section
            className="notice notice-warn text-[13px]"
            data-testid="admin-only"
          >
            <p className="font-semibold">This page is for admins.</p>
            <p className="mt-1 text-ink-2">
              Your token has the analyst or partner role, and the API refuses
              the admin routes to it (HTTP 403). Ask an admin, or use the keel
              CLI on the host.
            </p>
          </section>
        )}
        {known && (isAdmin || !adminOnly) && (
          <div key={version} className="space-y-3">
            {children(isAdmin)}
          </div>
        )}
      </main>
    </div>
  );
}
