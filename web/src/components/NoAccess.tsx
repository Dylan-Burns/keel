import type {FormEvent, JSX} from 'react';
import {useId, useState} from 'react';

/** Props of NoAccess. */
export interface NoAccessProps {
  /** What the token opens, such as "Enter your access token to ...". */
  readonly message: string;
  /** True after the API refused the stored token. */
  readonly rejected?: boolean;
  /** True while the server checks a token: the button waits. */
  readonly checking?: boolean;
  /** Saves the token, as the token field of the top bar does. */
  readonly onSave: (token: string) => void;
}

/**
 * The screen of the access gate: the Keel logo, what the token opens, and
 * a field to enter it. The page keeps the token in
 * session storage only (chapter 14.4 and control S-14).
 *
 * @param props The message, the refused flag, and the save action.
 * @return The screen.
 */
export function NoAccess({
  message,
  rejected = false,
  checking = false,
  onSave,
}: NoAccessProps): JSX.Element {
  const [value, setValue] = useState('');
  const inputId = useId();
  const submit = (event: FormEvent): void => {
    event.preventDefault();
    const token = value.trim();
    if (token !== '') {
      onSave(token);
      setValue('');
    }
  };
  return (
    <section
      className="panel flex w-full max-w-md flex-col items-center gap-4 px-6 py-8 text-center"
      aria-labelledby={`${inputId}-title`}
      data-testid="no-access"
    >
      <span className="keel-mark size-14" aria-hidden="true" />
      <div className="space-y-1.5">
        <h2
          id={`${inputId}-title`}
          className="font-mono text-[13px] font-bold uppercase tracking-[0.16em] text-ink"
        >
          {rejected ? 'Access token rejected' : 'Access token required'}
        </h2>
        <p
          className="text-[13px] text-ink-2"
          role={rejected ? 'alert' : undefined}
        >
          {message}
        </p>
      </div>
      <form className="flex w-full max-w-xs flex-col gap-2" onSubmit={submit}>
        <label className="sr-only" htmlFor={inputId}>
          Access token
        </label>
        <input
          id={inputId}
          type="password"
          autoComplete="off"
          placeholder="Access token"
          className="input w-full"
          value={value}
          onChange={event => setValue(event.target.value)}
          data-testid="no-access-token"
        />
        <button
          type="submit"
          className="btn btn-primary w-full"
          disabled={checking}
        >
          {checking ? 'Checking the token' : 'Continue'}
        </button>
      </form>
    </section>
  );
}
