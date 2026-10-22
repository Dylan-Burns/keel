import type {JSX, ReactNode} from 'react';

/** Props of OpsPanelHead. */
export interface OpsPanelHeadProps {
  /** The panel title, an h2. */
  readonly title: string;
  /** The CLI twin, shown at the right in mono, such as `keel add TICKER`. */
  readonly note?: string;
  /** Controls at the right of the strip. */
  readonly children?: ReactNode;
}

/**
 * The title strip of an operations panel: the title, the CLI command it
 * runs, and optional controls.
 *
 * @param props The props.
 * @return The strip.
 */
export function OpsPanelHead({
  title,
  note,
  children,
}: OpsPanelHeadProps): JSX.Element {
  return (
    <div className="panel-head">
      <h2 className="panel-title">{title}</h2>
      {note !== undefined && (
        <code className="hidden font-mono text-[10.5px] text-muted sm:inline">
          {note}
        </code>
      )}
      {children !== undefined && (
        <span className="ml-auto flex flex-wrap items-center gap-2">
          {children}
        </span>
      )}
    </div>
  );
}
