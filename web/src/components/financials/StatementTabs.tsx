import type {JSX, KeyboardEvent} from 'react';

/** 1 tab: a statement ID and its label. */
export interface StatementTab {
  readonly id: string;
  readonly label: string;
}

/** Props of StatementTabs. */
export interface StatementTabsProps {
  readonly tabs: readonly StatementTab[];
  /** The ID of the open statement. */
  readonly selected: string;
  readonly onSelect: (id: string) => void;
}

/**
 * The statement tabs of the financials page: Income Statement, Balance
 * Sheet, Cash Flow. The arrow keys move between tabs.
 *
 * @param props The props.
 * @return The tab list.
 */
export function StatementTabs({
  tabs,
  selected,
  onSelect,
}: StatementTabsProps): JSX.Element {
  const onKey = (event: KeyboardEvent<HTMLButtonElement>): void => {
    const step =
      event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (step === 0) {
      return;
    }
    event.preventDefault();
    const index = tabs.findIndex(tab => tab.id === selected);
    const next = tabs[(index + step + tabs.length) % tabs.length];
    if (next !== undefined) {
      onSelect(next.id);
      const list = event.currentTarget.parentElement;
      list
        ?.querySelector<HTMLButtonElement>(`[data-tab="${next.id}"]`)
        ?.focus();
    }
  };
  return (
    <div
      className="flex overflow-x-auto border-b border-line [scrollbar-width:none]"
      role="tablist"
      aria-label="Statements"
    >
      {tabs.map(tab => {
        const active = tab.id === selected;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            data-tab={tab.id}
            data-testid="fin-tab"
            className={`-mb-px whitespace-nowrap border-b-2 px-3.5 py-2 text-[12px] font-semibold ${
              active
                ? 'border-accent text-ink'
                : 'border-transparent text-muted hover:text-ink'
            }`}
            onClick={() => onSelect(tab.id)}
            onKeyDown={onKey}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
