import type {FormEvent, JSX} from 'react';
import {useState} from 'react';

/** Props of TokenField. */
export interface TokenFieldProps {
  /** True when session storage holds a token. */
  readonly hasToken: boolean;
  /** True after the API answered 401. */
  readonly rejected: boolean;
  readonly onSave: (token: string) => void;
}

/**
 * The access token field. The page keeps the token in session storage only
 * (chapter 14.4 and control S-14).
 *
 * @param props The props.
 * @return The field.
 */
export function TokenField({
  hasToken,
  rejected,
  onSave,
}: TokenFieldProps): JSX.Element {
  const [value, setValue] = useState('');
  const [editing, setEditing] = useState(false);
  const submit = (event: FormEvent): void => {
    event.preventDefault();
    onSave(value.trim());
    setValue('');
    setEditing(false);
  };
  if (hasToken && !rejected && !editing) {
    return (
      <button
        type="button"
        className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted underline underline-offset-2 hover:text-accent"
        onClick={() => setEditing(true)}
      >
        Change token
      </button>
    );
  }
  return (
    <form className="flex items-center gap-2" onSubmit={submit}>
      <label
        className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted"
        htmlFor="keel-token"
      >
        {rejected ? 'Token rejected, enter it again' : 'Access token'}
      </label>
      <input
        id="keel-token"
        type="password"
        autoComplete="off"
        className="input w-36"
        value={value}
        onChange={event => setValue(event.target.value)}
      />
      <button type="submit" className="btn btn-primary">
        Save
      </button>
    </form>
  );
}
