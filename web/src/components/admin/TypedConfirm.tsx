import type {JSX, KeyboardEvent, ReactNode} from 'react';
import {useEffect, useId, useRef, useState} from 'react';

/** Props of TypedConfirm. */
export interface TypedConfirmProps {
  /** The heading, such as `Restore a backup`. */
  readonly title: string;
  /** The exact text the admin types; the API checks the same value. */
  readonly expected: string;
  /** What the action does and what it costs. */
  readonly children: ReactNode;
  /** The label of the confirm button. */
  readonly actionLabel: string;
  /** Runs with the typed text once it matches. */
  readonly onConfirm: (typed: string) => void;
  readonly onCancel: () => void;
  /** The `data-testid` of the panel. */
  readonly testId: string;
}

/**
 * An inline typed confirmation for a destructive or heavy job: the warning,
 * a field that must hold the exact expected text, and a confirm button that
 * stays off until it does. Escape cancels. It replaces `window.confirm`,
 * and the server checks the same text, so a skipped step fails there too.
 *
 * @param props The props.
 * @return The panel.
 */
export function TypedConfirm({
  title,
  expected,
  children,
  actionLabel,
  onConfirm,
  onCancel,
  testId,
}: TypedConfirmProps): JSX.Element {
  const [typed, setTyped] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const fieldId = useId();
  const hintId = useId();
  useEffect(() => {
    input.current?.focus();
  }, []);
  const matches = typed === expected;
  const onKey = (event: KeyboardEvent): void => {
    if (event.key === 'Escape') {
      onCancel();
    }
  };
  return (
    <form
      className="notice notice-down space-y-2 text-[13px]"
      aria-label={title}
      data-testid={testId}
      onSubmit={event => {
        event.preventDefault();
        if (matches) {
          onConfirm(typed);
        }
      }}
    >
      <p className="font-semibold">{title}</p>
      <div className="text-ink-2">{children}</div>
      <label className="block space-y-1" htmlFor={fieldId}>
        <span className="block text-[12px] text-ink-2">
          Type <code className="tag tag-down select-all">{expected}</code> to
          confirm.
        </span>
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={input}
          id={fieldId}
          className="input min-w-0 flex-1 font-mono sm:max-w-md"
          value={typed}
          autoComplete="off"
          spellCheck={false}
          aria-describedby={hintId}
          data-testid={`${testId}-input`}
          onKeyDown={onKey}
          onChange={event => setTyped(event.target.value)}
        />
        <button
          type="submit"
          className="btn btn-danger"
          disabled={!matches}
          data-testid={`${testId}-submit`}
        >
          {actionLabel}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
      <p id={hintId} className="text-[11.5px] text-muted" aria-live="polite">
        {typed === '' || matches
          ? matches
            ? 'The text matches.'
            : 'The button turns on when the text matches exactly.'
          : 'The text does not match yet.'}
      </p>
    </form>
  );
}
