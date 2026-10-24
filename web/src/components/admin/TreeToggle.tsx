import type {JSX, ReactNode} from 'react';

/** Props of TreeToggle. */
export interface TreeToggleProps {
  readonly open: boolean;
  readonly testId: string;
  readonly onToggle: () => void;
  /** The visible content after the chevron. */
  readonly children: ReactNode;
}

/**
 * The expander of a tree row of the company browser: a button, so Enter
 * and Space open it, with `aria-expanded` and a chevron that points down
 * when open.
 *
 * @param props The props.
 * @return The button.
 */
export function TreeToggle({
  open,
  testId,
  onToggle,
  children,
}: TreeToggleProps): JSX.Element {
  return (
    <button
      type="button"
      className="flex w-full min-w-0 items-center gap-2 text-left"
      aria-expanded={open}
      data-testid={testId}
      onClick={onToggle}
    >
      <svg
        viewBox="0 0 12 12"
        className={`h-3 w-3 shrink-0 text-muted ${open ? 'rotate-90' : ''}`}
        aria-hidden="true"
      >
        <path
          d="M4 2l4 4-4 4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        />
      </svg>
      {children}
    </button>
  );
}
