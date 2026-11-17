import type {FormEvent, JSX} from 'react';
import {useId, useState} from 'react';

import {getToken, setToken} from '../api/client';

/** Props of AdminSignIn. */
export interface AdminSignInProps {
  /**
   * Runs after the token changes. The default reloads the page, so the
   * access gate and the role probe check the new token.
   */
  readonly onChange?: () => void;
}

function reloadPage(): void {
  window.location.reload();
}

/**
 * The admin sign in of a public service: a quiet link that opens a field
 * for a Keel access token, kept in session storage like the token gate
 * keeps it. With a token stored, it offers Sign out instead. The page then
 * reloads: the access gate checks the token, and a wrong one is refused
 * there rather than turned into a visitor.
 *
 * @param props The change handler.
 * @return The control.
 */
export function AdminSignIn({
  onChange = reloadPage,
}: AdminSignInProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState('');
  const inputId = useId();
  const signedIn = getToken() !== null;
  const link =
    'font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted underline underline-offset-2 hover:text-accent';
  if (signedIn) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-ink-2">
          Signed in with a Keel access token.
        </span>
        <button
          type="button"
          className={link}
          data-testid="admin-sign-out"
          onClick={() => {
            setToken('');
            onChange();
          }}
        >
          Sign out
        </button>
      </div>
    );
  }
  if (!open) {
    return (
      <button
        type="button"
        className={link}
        data-testid="admin-sign-in"
        onClick={() => setOpen(true)}
      >
        Admin sign in
      </button>
    );
  }
  const submit = (event: FormEvent): void => {
    event.preventDefault();
    const token = value.trim();
    if (token === '') {
      return;
    }
    setToken(token);
    setValue('');
    onChange();
  };
  return (
    <form className="flex flex-wrap items-center gap-2" onSubmit={submit}>
      <label
        className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted"
        htmlFor={inputId}
      >
        Keel access token
      </label>
      <input
        id={inputId}
        type="password"
        autoComplete="off"
        className="input w-40"
        value={value}
        onChange={event => setValue(event.target.value)}
        data-testid="admin-token"
      />
      <button type="submit" className="btn">
        Sign in
      </button>
    </form>
  );
}
