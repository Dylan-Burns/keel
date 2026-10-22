import type {JSX} from 'react';

import {AdminShell} from './AdminShell';
import {UsersPanel} from './UsersPanel';

/**
 * The users page at `/users` (admins; `keel users`): the users and their
 * roles, a form that adds a user and shows the new token once, and a
 * remove button with an inline confirmation.
 *
 * @return The page.
 */
export function UsersPage(): JSX.Element {
  return (
    <AdminShell title="Users" current="users" adminOnly testId="users-page">
      {() => <UsersPanel />}
    </AdminShell>
  );
}
