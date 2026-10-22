import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import type {CompanyFindings} from '../api/types';
import {chipFor} from '../lib/citations';
import {complete, pick} from '../motion/presets';
import type {Run} from '../state';
import {CitationChip} from './CitationChip';

/** Props of FindingsGroup. */
export interface FindingsGroupProps {
  readonly run: Run;
  readonly company: CompanyFindings;
  readonly onSelectCitation: (chunkId: string) => void;
}

/**
 * The findings of 1 company as an expandable group. A finding without a
 * valid citation shows `unverified`; the page never hides it.
 *
 * @param props The props.
 * @return The group.
 */
export function FindingsGroup({
  run,
  company,
  onSelectCitation,
}: FindingsGroupProps): JSX.Element {
  const reduced = useReducedMotion();
  const clickable = run.final !== null;
  return (
    <details
      className="rounded-lg border border-slate-200 bg-white"
      data-testid="findings-group"
      open
    >
      <summary className="cursor-pointer px-3 py-2 font-medium">
        {company.company} ({company.ticker})
      </summary>
      <motion.div
        className="overflow-hidden"
        variants={pick(complete.findings, reduced)}
        initial="hidden"
        animate="visible"
      >
        <motion.ul
          className="space-y-2 px-4 pb-3"
          variants={pick(complete.chips, reduced)}
          initial="hidden"
          animate={clickable ? 'visible' : 'hidden'}
        >
          {company.findings.map((finding, index) => (
            <li key={index} className="text-sm leading-relaxed">
              <span>{finding.point}</span>{' '}
              {finding.unverified === true ? (
                <CitationChip
                  chunkId=""
                  label="unverified"
                  valid={false}
                  clickable={false}
                  onSelect={onSelectCitation}
                />
              ) : (
                finding.citations.map(id => {
                  const chip = chipFor(run, id);
                  return (
                    <span key={id} className="mr-1 inline-block">
                      <CitationChip
                        chunkId={id}
                        label={chip.label}
                        valid={chip.valid}
                        clickable={clickable}
                        onSelect={onSelectCitation}
                      />
                    </span>
                  );
                })
              )}
            </li>
          ))}
        </motion.ul>
      </motion.div>
    </details>
  );
}
