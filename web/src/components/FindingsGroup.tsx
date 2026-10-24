import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import type {CompanyFindings} from '../api/types';
import {chipFor} from '../lib/citations';
import {TICKER_SHAPE, financialsPath} from '../lib/links';
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
      className="group border border-line bg-panel"
      data-testid="findings-group"
      open
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 bg-head px-2.5 py-1.5 [&::-webkit-details-marker]:hidden">
        <span
          className="inline-block w-2 font-mono text-[10px] text-muted group-open:rotate-90"
          aria-hidden="true"
        >
          &gt;
        </span>
        {/* The ticker comes from the model: only a ticker's shape links. */}
        {TICKER_SHAPE.test(company.ticker) ? (
          <a
            className="tag tag-accent font-semibold hover:underline"
            href={financialsPath(company.ticker)}
            title={`Financial statements of ${company.ticker}`}
            data-testid="company-financials-link"
          >
            {company.ticker}
          </a>
        ) : (
          <span className="tag tag-accent font-semibold">{company.ticker}</span>
        )}
        <span className="truncate font-medium text-ink">{company.company}</span>
        <span className="num ml-auto text-[10.5px] text-muted">
          {company.findings.length}{' '}
          {company.findings.length === 1 ? 'finding' : 'findings'}
        </span>
      </summary>
      <motion.div
        className="overflow-hidden"
        variants={pick(complete.findings, reduced)}
        initial="hidden"
        animate="visible"
      >
        <motion.ul
          className="divide-y divide-line"
          variants={pick(complete.chips, reduced)}
          initial="hidden"
          animate={clickable ? 'visible' : 'hidden'}
        >
          {company.findings.map((finding, index) => (
            <li
              key={index}
              className="px-3 py-2 text-[13px] leading-relaxed text-ink-2"
            >
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
