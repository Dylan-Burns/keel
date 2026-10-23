import type {JSX} from 'react';

import {TEXT_DIRECTIVE} from '../lib/fragment';
import {isSecUrl} from '../lib/markdown';

/** Props of SecLink. */
export interface SecLinkProps {
  readonly url: string | null;
  /** The link text; the URL itself when absent. */
  readonly label?: string;
  /** Extra classes, such as `truncate` for a 1-line list row. */
  readonly className?: string;
}

/**
 * A link to the SEC that opens in a new tab. Only `https://www.sec.gov`
 * URLs render as links; any other URL renders as text (chapter 14.5). A
 * URL with a text fragment says that it jumps to the excerpt.
 *
 * @param props The props.
 * @return The link, the URL as text, or nothing.
 */
export function SecLink({
  url,
  label,
  className = '',
}: SecLinkProps): JSX.Element | null {
  if (url === null || url === '') {
    return null;
  }
  if (!isSecUrl(url)) {
    return (
      <span
        className={`block break-all text-muted ${className}`}
        data-testid="untrusted-url"
      >
        {url}
      </span>
    );
  }
  const deep = url.includes(TEXT_DIRECTIVE);
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className={`link block break-all ${className}`}
      data-testid="sec-link"
      data-deep={deep}
      title={
        deep
          ? 'Opens the filing on sec.gov, scrolled to the highlighted excerpt'
          : undefined
      }
    >
      {label ?? 'Open on sec.gov'}
      {deep && (
        <span className="ml-1.5 text-muted" data-testid="excerpt-hint">
          (jumps to the excerpt)
        </span>
      )}
    </a>
  );
}
