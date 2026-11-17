import type {JSX, ReactNode} from 'react';
import {useEffect, useState} from 'react';

import type {AccessMode} from '../api/access';
import {knownAccessMode, setAccessMode, toAccessMode} from '../api/access';
import {fetchReady, getToken, setToken} from '../api/client';
import {TokenGate} from './TokenGate';

/** Props of AccessGate. */
export interface AccessGateProps {
  /** The page. */
  readonly children: ReactNode;
}

/**
 * The gate in front of every page. It reads the access mode of
 * `/api/ready` first (no token needed). A public service lets a visitor
 * straight in: they ask with their own Anthropic API key, or read the
 * cached answers. A service in token mode keeps the token gate, and so does
 * a public service when the tab holds a token (an admin signing in): a
 * wrong token is refused there, never turned into a visitor, and the
 * visitor can drop it and go on. The tab remembers the mode, so a later
 * page load does not wait for the check; until the first answer, a tab
 * without a token shows an empty canvas rather than a gate that may not
 * apply.
 *
 * @param props The page.
 * @return The gate or the page.
 */
export function AccessGate({children}: AccessGateProps): JSX.Element {
  const [access, setAccess] = useState<AccessMode | null>(knownAccessMode);
  const [hasToken, setHasToken] = useState(() => getToken() !== null);
  useEffect(() => {
    let cancelled = false;
    fetchReady()
      .then(ready => {
        if (cancelled) {
          return;
        }
        const mode = toAccessMode(ready.access) ?? 'token';
        // The module value first: the page reads it as it mounts.
        setAccessMode(mode);
        setAccess(mode);
      })
      .catch(() => {
        // The page reports an unreachable service; the gate follows the
        // last known mode, else the token gate.
        if (!cancelled) {
          setAccess(current => current ?? 'token');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);
  if (access === 'public' && !hasToken) {
    return <>{children}</>;
  }
  if (access === null && !hasToken) {
    return (
      <div
        className="min-h-screen bg-canvas"
        data-testid="access-checking"
        aria-busy="true"
      />
    );
  }
  const onSkip = (): void => {
    setToken('');
    setHasToken(false);
  };
  return (
    <TokenGate {...(access === 'public' ? {onSkip} : {})}>{children}</TokenGate>
  );
}
