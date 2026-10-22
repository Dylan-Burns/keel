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
      className="flex gap-2 text-xs"
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
            className={`rounded-full px-3 py-1 ${lit ? 'bg-accent text-white' : 'bg-slate-200 text-slate-500'}`}
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
