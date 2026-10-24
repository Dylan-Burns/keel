import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';
import {useLayoutEffect, useRef, useState} from 'react';

import {financials, pick} from '../../motion/presets';

/** The filing behind a tooltip row. */
export interface TooltipSource {
  readonly form: string;
  /** The filing date, already formatted. */
  readonly filed: string;
  readonly url: string;
}

/** 1 series of the tooltip. */
export interface TooltipRow {
  readonly id: string;
  /** The color slot, 1 to 8. */
  readonly slot: number;
  readonly label: string;
  /** The value, already formatted, or `not reported`. */
  readonly value: string;
  readonly source: TooltipSource | null;
  readonly derived: boolean;
  /** The derivation or adjustment note, or null. */
  readonly note: string | null;
}

/** What the tooltip shows for 1 period. */
export interface TooltipContent {
  /** The period label, such as `Q2 FY2027`. */
  readonly title: string;
  /** The period dates. */
  readonly subtitle: string;
  readonly rows: readonly TooltipRow[];
}

/** Props of ChartTooltip. */
export interface ChartTooltipProps {
  readonly content: TooltipContent;
  /** The pointer position in the viewport. */
  readonly x: number;
  readonly y: number;
  /** A pinned tooltip takes the pointer and shows its close button. */
  readonly pinned: boolean;
  readonly onClose: () => void;
}

const GAP = 14;
const EDGE = 8;

/**
 * The chart tooltip of the financials page: every checked series of 1
 * period with its value and its source filing (form, filing date, and a
 * link to the filing on sec.gov), derived values flagged. Hovering shows
 * it; a click or Enter pins it so the links can be followed; Escape or a
 * click elsewhere closes it. It stays inside the viewport.
 *
 * @param props The props.
 * @return The tooltip.
 */
export function ChartTooltip({
  content,
  x,
  y,
  pinned,
  onClose,
}: ChartTooltipProps): JSX.Element {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState({left: x + GAP, top: y + GAP});
  useLayoutEffect(() => {
    const box = ref.current?.getBoundingClientRect();
    const width = box?.width ?? 0;
    const height = box?.height ?? 0;
    let left = x + GAP;
    if (left + width > window.innerWidth - EDGE) {
      left = Math.max(EDGE, x - width - GAP);
    }
    let top = y + GAP;
    if (top + height > window.innerHeight - EDGE) {
      top = Math.max(EDGE, y - height - GAP);
    }
    setPlace({left, top});
  }, [x, y, content]);
  return (
    <motion.div
      ref={ref}
      role={pinned ? 'dialog' : 'tooltip'}
      aria-label={`${content.title} values`}
      data-testid="fin-tooltip"
      data-pinned={pinned}
      className={`fixed z-50 min-w-[200px] max-w-[320px] border border-line-strong bg-panel text-[11px] shadow-[0_6px_20px_rgb(0_0_0/18%)] ${
        pinned ? 'pointer-events-auto' : 'pointer-events-none'
      }`}
      style={{left: place.left, top: place.top}}
      variants={pick(financials.tooltip, reduced)}
      initial="hidden"
      animate="visible"
    >
      <div className="flex items-center justify-between gap-2 border-b border-line bg-head px-2 py-1 font-bold">
        <span>{content.title}</span>
        <span className="num flex items-center gap-1 font-normal text-muted">
          {content.subtitle}
          {pinned && (
            <button
              type="button"
              className="px-0.5 text-muted hover:text-ink"
              aria-label="Close"
              data-testid="fin-tooltip-close"
              onClick={onClose}
            >
              x
            </button>
          )}
        </span>
      </div>
      {content.rows.map(row => (
        <div
          key={row.id}
          className="grid grid-cols-[10px_1fr_auto] items-center gap-x-1.5 px-2 py-0.5"
          data-testid="fin-tooltip-row"
        >
          <span
            className="inline-block h-2.5 w-2.5 rounded-[2px]"
            style={{background: `var(--k-s${row.slot})`}}
            aria-hidden="true"
          />
          <span>{row.label}</span>
          <span className="num text-right font-semibold">{row.value}</span>
          {(row.source !== null || row.note !== null) && (
            <span className="col-start-2 col-end-4 -mt-0.5 text-[10px] text-muted">
              {row.source !== null && (
                <>
                  {`${row.source.form} filed ${row.source.filed} `}
                  <a
                    className="link"
                    href={row.source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    tabIndex={pinned ? 0 : -1}
                  >
                    filing
                  </a>
                </>
              )}
              {row.note !== null && (
                <span className="block">
                  {row.derived && (
                    <span className="num mr-1 border border-current px-[3px] text-[9px] font-bold text-warn">
                      DERIVED
                    </span>
                  )}
                  {row.note}
                </span>
              )}
            </span>
          )}
        </div>
      ))}
      <div className="border-t border-line px-2 pb-1.5 pt-1 text-[10px] text-muted">
        {pinned
          ? 'Open a filing on sec.gov. Esc closes.'
          : 'Click to pin and open the filing. Esc closes.'}
      </div>
    </motion.div>
  );
}
