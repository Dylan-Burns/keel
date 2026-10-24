import type {JSX} from 'react';

/**
 * The Keel logo and name, as a link to the questions page at `/`. The
 * logo is a mask filled with the accent color, so it follows the theme.
 *
 * @return The link.
 */
export function BrandLink(): JSX.Element {
  return (
    <a
      href="/"
      className="group flex items-center gap-3 rounded-sm"
      title="Back to questions"
      data-testid="brand-link"
    >
      <span className="keel-mark size-10 shrink-0" aria-hidden="true" />
      <span className="font-mono text-[30px] font-bold leading-none uppercase tracking-[0.2em] text-ink group-hover:text-accent">
        Keel
      </span>
    </a>
  );
}
