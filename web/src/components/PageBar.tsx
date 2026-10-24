import type {JSX, ReactNode} from 'react';

import {ThemeToggle} from './ThemeToggle';
import {BrandLink} from './BrandLink';

/** Props of PageBar. */
export interface PageBarProps {
  /** The page name, the h1 of the page. */
  readonly title: string;
  /** The token field, when the page reads the API. */
  readonly children?: ReactNode;
}

/**
 * The top bar of a secondary page (history, comp sets, eval, data use): the
 * name, the page title, the way back to the questions, the theme toggle, and
 * the token field.
 *
 * @param props The props.
 * @return The bar.
 */
export function PageBar({title, children}: PageBarProps): JSX.Element {
  return (
    <header className="z-30 border-b border-line bg-panel md:sticky md:top-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-1.5">
        <BrandLink />
        <span className="font-mono text-muted" aria-hidden="true">
          /
        </span>
        <h1 className="font-mono text-[12px] font-semibold uppercase tracking-[0.14em] text-ink">
          {title}
        </h1>
        <button
          type="button"
          className="btn sm:ml-2"
          onClick={() => window.location.assign('/')}
        >
          Back to questions
        </button>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <ThemeToggle />
          {children}
        </div>
      </div>
    </header>
  );
}
