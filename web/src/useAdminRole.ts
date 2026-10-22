import {useEffect, useState} from 'react';

import {probeAdmin} from './api/admin';
import {ApiError, getToken} from './api/client';

/** What the page knows of the caller's role. */
export type RoleState =
  | {readonly kind: 'no_token'}
  | {readonly kind: 'loading'}
  | {readonly kind: 'rejected'}
  | {readonly kind: 'admin'}
  | {readonly kind: 'member'}
  | {readonly kind: 'error'; readonly message: string};

/**
 * The role of the stored token, from a probe of an admin route: HTTP 200 is
 * an admin, 403 an analyst or a partner, 401 a rejected token. The page uses
 * it only to choose what to show; the API checks the role on every call.
 *
 * @param version A counter the page bumps when the token changes.
 * @return The role state.
 */
export function useAdminRole(version: number): RoleState {
  const [role, setRole] = useState<RoleState>(() =>
    getToken() === null ? {kind: 'no_token'} : {kind: 'loading'},
  );
  const [seen, setSeen] = useState(version);
  if (seen !== version) {
    // A new token: probe again (the render-time reset of React docs).
    setSeen(version);
    setRole(getToken() === null ? {kind: 'no_token'} : {kind: 'loading'});
  }
  useEffect(() => {
    if (getToken() === null) {
      return;
    }
    let cancelled = false;
    probeAdmin()
      .then(admin => {
        if (!cancelled) {
          setRole({kind: admin ? 'admin' : 'member'});
        }
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          setRole({kind: 'rejected'});
        } else {
          setRole({kind: 'error', message: 'The role check failed.'});
        }
      });
    return () => {
      cancelled = true;
    };
  }, [version]);
  return role;
}
