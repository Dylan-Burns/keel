import type {JSX, ReactNode} from 'react';
import {useState} from 'react';

import {setToken} from '../api/client';
import {useAdminRole} from '../useAdminRole';
import {NoAccess} from './NoAccess';

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
 * network fault does not lock a user out; the page reports it.
 *
 * @param props The page.
 * @return The gate or the page.
 */
export function AccessGate({children}: AccessGateProps): JSX.Element {
  const [version, setVersion] = useState(0);
  const role = useAdminRole(version);
  if (
    role.kind === 'admin' ||
    role.kind === 'member' ||
    role.kind === 'error'
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
