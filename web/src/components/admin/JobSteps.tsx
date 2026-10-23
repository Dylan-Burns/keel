import type {JSX} from 'react';
import {useEffect, useState} from 'react';

import type {JobStep} from '../../api/types';
import {JobStepRow} from './JobStepRow';

/** The tick of the running step's duration. */
export const TICK_MS = 1000;

/** Props of JobSteps. */
export interface JobStepsProps {
  readonly jobId: string;
  readonly steps: readonly JobStep[];
}

/**
 * True when a step's log opens by itself: the running step and a failed
 * step.
 *
 * @param step The step.
 * @return True to open it.
 */
export function opensByItself(step: JobStep): boolean {
  return step.status === 'running' || step.status === 'failed';
}

/**
 * The steps of a job as a CI run shows them: 1 row per step in order, each
 * with its mark, name, duration, counts, and log. The running step and a
 * failed step open their log by themselves, and a step closes again when it
 * ends; a step the reader opened or closed stays as they left it. The
 * duration of the running step ticks every second.
 *
 * @param props The props.
 * @return The list.
 */
export function JobSteps({jobId, steps}: JobStepsProps): JSX.Element {
  const [chosen, setChosen] = useState<Readonly<Record<string, boolean>>>({});
  const now = useNow(steps.some(step => step.status === 'running'));
  const onToggle = (key: string): void => {
    setChosen(current => {
      const step = steps.find(s => s.key === key);
      const open = current[key] ?? (step ? opensByItself(step) : false);
      return {...current, [key]: !open};
    });
  };
  return (
    <ol
      className="border border-line bg-panel"
      aria-label="Job steps"
      data-testid="job-steps"
    >
      {steps.map((step, index) => (
        <JobStepRow
          key={step.key}
          jobId={jobId}
          index={index}
          step={step}
          open={chosen[step.key] ?? opensByItself(step)}
          onToggle={onToggle}
          now={now}
        />
      ))}
    </ol>
  );
}

/**
 * The clock, ticking every second while `active`. A stale first value
 * reads as 0s, because a duration never goes below 0.
 *
 * @param active True while a step runs.
 * @return The time in milliseconds.
 */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) {
      return undefined;
    }
    const timer = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}
