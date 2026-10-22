import type {JSX} from 'react';
import {useEffect, useState} from 'react';

import {addUser, fetchUsers, removeUser} from '../../api/admin';
import {ApiError} from '../../api/client';
import type {Role, UserCreated, UserList} from '../../api/types';
import {NewTokenNotice} from './NewTokenNotice';
import {OpsPanelHead} from './OpsPanelHead';

/** A user name as the API takes it. */
const USER_NAME = /^[a-z0-9._-]{1,64}$/;

/** The roles in the order of the select. */
const ROLES: readonly Role[] = ['analyst', 'partner', 'admin'];

/** The load state of the list. */
type Load =
  | {readonly kind: 'loading'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly data: UserList};

/**
 * The page text of a failed add or remove.
 *
 * @param error The error.
 * @param fallback The text of an unknown error.
 * @return The text.
 */
function messageOf(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'user_exists':
        return 'A user with this name exists.';
      case 'self_delete':
        return 'You cannot remove your own user.';
      case 'invalid_user':
        return 'The name legacy is reserved for KEEL_API_TOKEN.';
      default:
        return error.status === 422
          ? 'A name has lowercase letters, digits, dots, underscores, or dashes.'
          : error.message;
    }
  }
  return fallback;
}

/**
 * The users panels (`keel users`): the add form with the new token shown
 * once, and the users with an inline remove confirmation.
 *
 * @return The panels.
 */
export function UsersPanel(): JSX.Element {
  const [load, setLoad] = useState<Load>({kind: 'loading'});
  const [version, setVersion] = useState(0);
  const [name, setName] = useState('');
  const [role, setRole] = useState<Role>('analyst');
  const [created, setCreated] = useState<UserCreated | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetchUsers()
      .then(data => {
        if (!cancelled) {
          setLoad({kind: 'ready', data});
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoad({kind: 'error', message: 'The users could not load.'});
        }
      });
    return () => {
      cancelled = true;
    };
  }, [version]);
  const onAdd = (): void => {
    const value = name.trim();
    if (!USER_NAME.test(value)) {
      setNotice(
        'A name has 1 to 64 lowercase letters, digits, dots, underscores, or dashes.',
      );
      return;
    }
    setNotice(null);
    setSending(true);
    addUser(value, role)
      .then(user => {
        setCreated(user);
        setName('');
        setVersion(n => n + 1);
      })
      .catch((error: unknown) =>
        setNotice(messageOf(error, 'The user could not be added.')),
      )
      .finally(() => setSending(false));
  };
  const onRemove = (user: string): void => {
    removeUser(user)
      .then(() => {
        setNotice(`Removed ${user}. The token stops passing now.`);
        setRemoving(null);
        setVersion(n => n + 1);
      })
      .catch((error: unknown) => {
        setNotice(messageOf(error, `${user} could not be removed.`));
        setRemoving(null);
      });
  };
  return (
    <>
      <section className="panel" aria-label="Add a user">
        <OpsPanelHead title="Add a user" note="keel users add NAME --role" />
        <div className="panel-body space-y-3">
          <form
            className="flex flex-wrap items-end gap-2"
            data-testid="user-form"
            onSubmit={event => {
              event.preventDefault();
              onAdd();
            }}
          >
            <label className="flex flex-col gap-1">
              <span className="section-title">Name</span>
              <input
                className="input w-48 max-w-full font-mono"
                value={name}
                placeholder="dave"
                maxLength={64}
                autoComplete="off"
                data-testid="user-name"
                onChange={event => setName(event.target.value.toLowerCase())}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="section-title">Role</span>
              <select
                className="input h-[1.875rem]"
                value={role}
                data-testid="user-role"
                onChange={event => setRole(event.target.value as Role)}
              >
                {ROLES.map(r => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={sending}
              data-testid="user-add"
            >
              Add user
            </button>
          </form>
          {created !== null && (
            <NewTokenNotice user={created} onDismiss={() => setCreated(null)} />
          )}
          {notice !== null && (
            <p
              className="font-mono text-[12px] text-ink-2"
              role="status"
              data-testid="user-notice"
            >
              {notice}
            </p>
          )}
        </div>
      </section>
      <section className="panel" aria-label="Users" data-testid="users">
        <OpsPanelHead title="Users" note="keel users list" />
        {load.kind === 'loading' && (
          <p className="panel-body text-[12px] text-muted">
            Loading the users.
          </p>
        )}
        {load.kind === 'error' && (
          <p className="panel-body text-[12px] text-down" role="alert">
            {load.message}
          </p>
        )}
        {load.kind === 'ready' && (
          <div className="overflow-x-auto">
            <table className="grid-table" data-testid="users-table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Role</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {load.data.legacy_enabled && (
                  <tr data-testid="users-legacy">
                    <td className="font-mono">legacy</td>
                    <td>
                      <span className="tag tag-accent">admin</span>
                    </td>
                    <td className="text-right text-[12px] text-muted">
                      KEEL_API_TOKEN; unset it to retire
                    </td>
                  </tr>
                )}
                {load.data.items.map(user => (
                  <tr
                    key={user.name}
                    data-testid="users-row"
                    data-name={user.name}
                  >
                    <td className="font-mono">{user.name}</td>
                    <td>
                      <span
                        className={`tag ${user.role === 'admin' ? 'tag-accent' : ''}`}
                      >
                        {user.role}
                      </span>
                    </td>
                    <td className="text-right">
                      {removing === user.name ? (
                        <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                          <span className="text-[12px] text-ink-2">
                            Remove {user.name}? The token stops at once.
                          </span>
                          <button
                            type="button"
                            className="btn btn-danger"
                            data-testid="user-remove-confirm"
                            onClick={() => onRemove(user.name)}
                          >
                            Remove
                          </button>
                          <button
                            type="button"
                            className="btn"
                            onClick={() => setRemoving(null)}
                          >
                            Keep
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="btn"
                          aria-label={`Remove ${user.name}`}
                          data-testid="user-remove"
                          onClick={() => setRemoving(user.name)}
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {load.data.items.length === 0 && (
              <p
                className="px-3 py-2 text-[12px] text-muted"
                data-testid="users-empty"
              >
                No users in the users file yet.
              </p>
            )}
          </div>
        )}
      </section>
    </>
  );
}
