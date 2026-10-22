import type {JSX} from 'react';

import {isSecUrl} from '../lib/markdown';

/** Props of SecLink. */
export interface SecLinkProps {
  readonly url: string | null;
  /** The link text; the URL itself when absent. */
  readonly label?: string;
}

/**
 * A link to the SEC that opens in a new tab. Only `https://www.sec.gov`
 * URLs render as links; any other URL renders as text (chapter 14.5).
 *
 * @param props The props.
 * @return The link, the URL as text, or nothing.
 */
export function SecLink({url, label}: SecLinkProps): JSX.Element | null {
  if (url === null || url === '') {
    return null;
  }
  if (!isSecUrl(url)) {
    return (
      <span
        className="block break-all text-slate-500"
        data-testid="untrusted-url"
      >
        {url}
      </span>
    );
  }
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="block break-all text-accent underline"
      data-testid="sec-link"
    >
      {label ?? 'Open on sec.gov'}
    </a>
  );
}
