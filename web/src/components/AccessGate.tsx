import type {JSX, ReactNode} from 'react';
import {useEffect, useState} from 'react';

import {getToken, setToken} from '../api/client';
import {useAdminRole} from '../useAdminRole';
import {NoAccess} from './NoAccess';

/** The session key of the fingerprint of the last accepted token. */
export const ACCEPTED_KEY = 'keel.token.accepted';

/**
 * A short fingerprint of a token, so the tab can remember which token the
 * server accepted without a second copy of the token itself.
 *
 * @param token The token.
 * @return The fingerprint, 8 hex digits.
 */
export function fingerprint(token: string): string {
  let hash = 2166136261;
  for (let i = 0; i < token.length; i++) {
    hash = Math.imul(hash ^ token.charCodeAt(i), 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}

/** True when the server accepted the stored token earlier in this tab. */
function acceptedBefore(): boolean {
  const token = getToken();
  try {
    return (
      token !== null &&
      window.sessionStorage.getItem(ACCEPTED_KEY) === fingerprint(token)
    );
  } catch {
    return false;
  }
}

/** Remembers the stored token as accepted, or forgets it. */
function remember(accepted: boolean): void {
  const token = getToken();
  try {
    if (accepted && token !== null) {
      window.sessionStorage.setItem(ACCEPTED_KEY, fingerprint(token));
    } else {
      window.sessionStorage.removeItem(ACCEPTED_KEY);
    }
  } catch {
    // Storage blocked: every page load checks the token first.
  }
}

/** Props of AccessGate. */
export interface AccessGateProps {
  /** The page, shown once the server accepts the token. */
  readonly children: ReactNode;
}

/**
 * The gate in front of every page: without a token the app shows only the
 * Keel logo and a token field. The server checks the token (the role probe
 * of `useAdminRole`) before the page renders; a refused token stays at the
 * gate. A failed check for any other reason lets the page through, so a
 * network fault does not lock a user out; the page reports it. Each page
 * link is a full page load, so the tab remembers the accepted token: a
 * later load renders the page at once while the check runs again, and a
 * refusal then returns to the gate.
 *
 * @param props The page.
 * @return The gate or the page.
 */
export function AccessGate({children}: AccessGateProps): JSX.Element {
  const [version, setVersion] = useState(0);
  const role = useAdminRole(version);
  const [known] = useState(acceptedBefore);
  useEffect(() => {
    if (role.kind === 'admin' || role.kind === 'member') {
      remember(true);
    } else if (role.kind === 'rejected' || role.kind === 'no_token') {
      remember(false);
    }
  }, [role.kind]);
  if (
    role.kind === 'admin' ||
    role.kind === 'member' ||
    role.kind === 'error' ||
    (role.kind === 'loading' && known && version === 0)
  ) {
    return <>{children}</>;
  }
  const onSave = (token: string): void => {
    setToken(token);
    setVersion(n => n + 1);
  };
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-4 font-sans text-ink">
      <NoAccess
        message={
          role.kind === 'rejected'
            ? 'The server did not accept this token. Check it and try again.'
            : 'Enter your access token to use Keel.'
        }
        rejected={role.kind === 'rejected'}
        checking={role.kind === 'loading'}
        onSave={onSave}
      />
    </div>
  );
}
