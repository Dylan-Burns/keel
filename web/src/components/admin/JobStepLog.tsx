import type {JSX} from 'react';
import {useLayoutEffect, useRef} from 'react';

/** Props of JobStepLog. */
export interface JobStepLogProps {
  /** The id the step header points at with `aria-controls`. */
  readonly id: string;
  /** The step name, for the label of the log. */
  readonly name: string;
  readonly lines: readonly string[];
  /** True while the step runs: an empty log says it waits for output. */
  readonly live: boolean;
}

/** How close to the bottom, in pixels, still counts as following. */
export const FOLLOW_SLACK_PX = 8;

/**
 * The log of 1 job step: numbered monospace lines, as a CI run shows them.
 * It follows the newest line while the reader is at the bottom and stops
 * following once the reader scrolls up, until they scroll back down. Each
 * line is a JSX text node; the runner already masked secrets and removed
 * control characters.
 *
 * @param props The props.
 * @return The log panel.
 */
export function JobStepLog({
  id,
  name,
  lines,
  live,
}: JobStepLogProps): JSX.Element {
  const box = useRef<HTMLOListElement>(null);
  const following = useRef(true);
  const onScroll = (): void => {
    const el = box.current;
    if (el === null) {
      return;
    }
    following.current =
      el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_SLACK_PX;
  };
  const newest = lines[lines.length - 1];
  useLayoutEffect(() => {
    const el = box.current;
    if (el !== null && following.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [lines.length, newest]);
  if (lines.length === 0) {
    return (
      <p
        id={id}
        className="border-t border-line bg-field px-3 py-1.5 pl-9 font-mono text-[11px] text-muted"
        data-testid="job-step-log"
      >
        {live ? 'Waiting for output.' : 'No output.'}
      </p>
    );
  }
  return (
    <ol
      id={id}
      ref={box}
      onScroll={onScroll}
      className="max-h-72 overflow-y-auto border-t border-line bg-field py-1 font-mono text-[11px] leading-[1.6] text-ink-2"
      role="log"
      aria-label={`${name} log`}
      aria-live="off"
      data-testid="job-step-log"
    >
      {lines.map((line, index) => (
        <li
          key={index}
          className="grid grid-cols-[2.75rem_minmax(0,1fr)] gap-2 pr-3 hover:bg-raised"
        >
          <span
            className="select-none text-right text-muted tabular-nums"
            aria-hidden="true"
          >
            {index + 1}
          </span>
          <span className="whitespace-pre-wrap break-words">{line}</span>
        </li>
      ))}
    </ol>
  );
}
