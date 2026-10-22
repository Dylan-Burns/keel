import type {JSX} from 'react';
import {useState} from 'react';

import type {UserCreated} from '../../api/types';
import {copyText} from '../../lib/links';

/** Props of NewTokenNotice. */
export interface NewTokenNoticeProps {
  /** The new user with the token of the 201 response. */
  readonly user: UserCreated;
  /** Drops the token from the page state. */
  readonly onDismiss: () => void;
}

/**
 * The token of a new user, shown once: the server keeps only its hash, so
 * the page shows it here, offers a copy button, and forgets it on dismiss.
 * The token never goes to storage, a log, or the URL.
 *
 * @param props The props.
 * @return The notice.
 */
export function NewTokenNotice({
  user,
  onDismiss,
}: NewTokenNoticeProps): JSX.Element {
  const [copied, setCopied] = useState<string | null>(null);
  return (
    <section
      className="notice notice-warn space-y-2 text-[13px]"
      aria-label={`Token of ${user.name}`}
      data-testid="new-token"
    >
      <p className="font-semibold">
        Token of {user.name} ({user.role}). It won&apos;t be shown again.
      </p>
      <p className="text-ink-2">
        Copy it now and hand it to {user.name} over a private channel. The
        server keeps only its hash; a lost token means removing the user and
        adding them again.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <code
          className="min-w-0 max-w-full select-all break-all border border-line-strong bg-field px-2 py-1 font-mono text-[12.5px] text-ink"
          data-testid="new-token-value"
        >
          {user.token}
        </code>
        <button
          type="button"
          className="btn btn-primary"
          data-testid="new-token-copy"
          onClick={() =>
            copyText(user.token)
              .then(() => setCopied('Copied'))
              .catch(() => setCopied('Copy failed: select the token instead'))
          }
        >
          Copy token
        </button>
        <button
          type="button"
          className="btn"
          data-testid="new-token-dismiss"
          onClick={onDismiss}
        >
          Done
        </button>
        {copied !== null && (
          <span className="font-mono text-[11px] text-up" role="status">
            {copied}
          </span>
        )}
      </div>
    </section>
  );
}
