import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import type {PipelineStep, Run} from '../state';
import {pick, questionSent} from '../motion/presets';
import {PIPELINE_STEPS} from '../state';

/** Props of ProgressSteps. */
export interface ProgressStepsProps {
  readonly run: Run;
  /** True once the first `answer_delta` arrived: the pulse stops. */
  readonly streaming: boolean;
}

const LABELS: Readonly<Record<PipelineStep, string>> = {
  understanding: 'Understanding',
  retrieval: 'Retrieval',
  model: 'Model',
};

/**
 * The progress line of the loading state: 3 steps that light up as the
 * `meta`, `analysis`, and `retrieval` events arrive.
 *
 * @param props The props.
 * @return The progress line.
 */
export function ProgressSteps({
  run,
  streaming,
}: ProgressStepsProps): JSX.Element {
  const reduced = useReducedMotion();
  const last = run.stepsLit[run.stepsLit.length - 1];
  return (
    <ol
      className="flex items-center gap-1"
      aria-label="Pipeline progress"
      data-testid="progress-steps"
      data-order={run.stepsLit.join(',')}
    >
      {PIPELINE_STEPS.map(step => {
        const lit = run.stepsLit.includes(step);
        const active = lit && step === last && !streaming && run.final === null;
        return (
          <motion.li
            key={step}
            variants={pick(questionSent.step, reduced)}
            initial="off"
            animate={active ? 'pulse' : lit ? 'lit' : 'off'}
            className={`border px-1.5 py-px font-mono text-[10px] uppercase tracking-[0.1em] ${lit ? 'border-accent bg-accent text-on-accent' : 'border-line-strong text-muted'}`}
            data-step={step}
            data-lit={lit}
            data-active={active}
          >
            {LABELS[step]}
          </motion.li>
        );
      })}
    </ol>
  );
}
