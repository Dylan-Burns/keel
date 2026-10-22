import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';
import {useState} from 'react';

import type {AuditRecord} from '../api/types';
import {pick, traceDrawer} from '../motion/presets';

/** Props of TraceDrawer. */
export interface TraceDrawerProps {
  /** The audit record that the `final` event carries. */
  readonly audit: AuditRecord;
}

/** 1 line of the trace: a label and its value, in pipeline order. */
export interface TraceLine {
  readonly label: string;
  readonly value: string;
}

/** The trace lines before and after the request line. */
export interface TraceLines {
  readonly before: TraceLine[];
  readonly after: TraceLine[];
}

const NUMBER = new Intl.NumberFormat('en-US');

/**
 * Formats a count with thousands separators, or `n/a`.
 *
 * @param value The number.
 * @return The text.
 */
function count(value: number | null | undefined): string {
  return value === null || value === undefined ? 'n/a' : NUMBER.format(value);
}

/**
 * Formats a latency in milliseconds as seconds, or `n/a`.
 *
 * @param ms The milliseconds.
 * @return The text, such as `8.1 s`.
 */
function seconds(ms: number | null | undefined): string {
  return ms === null || ms === undefined
    ? 'n/a'
    : `${(ms / 1000).toFixed(1)} s`;
}

/**
 * The literal request line of chapter 25.1: `model requests: 1`, or with a
 * retry before content `model requests: 2 (1 failed before content)`.
 *
 * @param audit The audit record.
 * @return The line.
 */
export function requestLine(audit: AuditRecord): string {
  const failed = audit.failed_before_content ?? 0;
  const base = `model requests: ${audit.model_requests}`;
  return failed > 0 ? `${base} (${failed} failed before content)` : base;
}

/**
 * The lines of the trace in pipeline order: understanding, retrieval, the
 * context, the prompt, the model, the usage, the latency, the validator, and
 * the flags. The request line is separate, so it can pulse.
 *
 * @param audit The audit record.
 * @return The lines before and after the request line.
 */
export function traceLines(audit: AuditRecord): TraceLines {
  const before: TraceLine[] = [];
  const after: TraceLine[] = [];
  const tickers = audit.tickers ?? [];
  before.push({
    label: 'entities',
    value: tickers.length > 0 ? tickers.join(', ') : 'none',
  });
  const scope = audit.time_scope ? `, time scope ${audit.time_scope}` : '';
  before.push({
    label: 'question type',
    value: `${audit.question_type ?? 'n/a'}${scope}`,
  });
  for (const filter of audit.filters ?? []) {
    const parts = [
      filter.tickers.length > 0 ? filter.tickers.join(' ') : 'all companies',
      filter.sections.length > 0 ? filter.sections.join(' ') : 'all sections',
    ];
    if (filter.filings > 0) {
      parts.push(`${filter.filings} filings`);
    }
    for (const [ticker, start, end] of filter.windows) {
      parts.push(`${ticker} ${start} to ${end}`);
    }
    before.push({label: `filter ${filter.label}`, value: parts.join('; ')});
  }
  const candidates = audit.candidates;
  if (candidates !== null && candidates !== undefined) {
    before.push({
      label: 'candidates',
      value: `${count(candidates.gathered)} gathered, ${count(candidates.reranked)} reranked, ${count(candidates.collapsed)} near-duplicates collapsed`,
    });
    for (const company of candidates.per_company) {
      before.push({
        label: `candidates ${company.ticker}`,
        value: `${count(company.before)} before collapse, ${count(company.after)} after`,
      });
    }
  }
  for (const fill of audit.quota_fills ?? []) {
    before.push({
      label: `quota ${fill.label}`,
      value: `${count(fill.taken)} of ${count(fill.quota)}`,
    });
  }
  before.push({
    label: 'context',
    value: `${count(audit.chunk_count)} chunks, ${count(audit.token_estimate)} estimated tokens`,
  });
  if (audit.facts_lines !== undefined) {
    const source = audit.facts_source ? ` from ${audit.facts_source}` : '';
    const ids = audit.fact_ids?.length ?? 0;
    before.push({
      label: 'facts',
      value: `${count(audit.facts_lines)} lines${source}, ${count(ids)} fact IDs`,
    });
  }
  before.push({
    label: 'prompt',
    value: `${audit.prompt_version ?? 'n/a'}, ${audit.prompt_hash ?? 'n/a'}`,
  });
  before.push({label: 'index', value: audit.index_version ?? 'n/a'});
  before.push({label: 'model', value: audit.model ?? 'n/a'});
  const usage = audit.usage ?? {};
  after.push({
    label: 'tokens',
    value: `${count(usage.input_tokens)} input, ${count(usage.cached_input_tokens)} cached, ${count(usage.output_tokens)} output`,
  });
  after.push({
    label: 'cost',
    value:
      audit.cost_usd === undefined ? 'n/a' : `$${audit.cost_usd.toFixed(4)}`,
  });
  const latency = audit.latency_ms ?? {};
  after.push({
    label: 'latency',
    value: `first token ${seconds(latency.first_token)}, total ${seconds(latency.total)}`,
  });
  after.push({
    label: 'citation drift',
    value: `${count(audit.citation_drift ?? 0)} dropped, ${count(audit.unverified ?? 0)} unverified findings`,
  });
  const flags = audit.flags ?? {};
  const raised = [
    flags.from_cache === true ? 'from_cache' : null,
    flags.degraded === true ? 'degraded' : null,
    flags.injection_suspect === true ? 'injection_suspect' : null,
    flags.schema_violation === true ? 'schema_violation' : null,
  ].filter((flag): flag is string => flag !== null);
  if (raised.length > 0) {
    after.push({label: 'flags', value: raised.join(', ')});
  }
  if (audit.error) {
    after.push({label: 'error', value: audit.error});
  }
  return {before, after};
}

/**
 * Renders a list of trace lines.
 *
 * @param lines The lines.
 * @return The rows.
 */
function rows(lines: readonly TraceLine[]): JSX.Element[] {
  return lines.map((line, index) => (
    <div
      key={`${line.label}-${index}`}
      className="grid grid-cols-[10rem_minmax(0,1fr)] gap-2"
    >
      <dt className="text-slate-500">{line.label}</dt>
      <dd className="break-words text-slate-800">{line.value}</dd>
    </div>
  ));
}

/**
 * The answer-trace drawer (W-01, chapter 25.1): the audit record of the
 * answer in pipeline order, with the literal line `model requests: 1`. It
 * springs up under the answer, and the request line pulses once per answer
 * (the parent keys the drawer by request ID). Every value renders as a JSX
 * text node.
 *
 * @param props The props.
 * @return The drawer.
 */
export function TraceDrawer({audit}: TraceDrawerProps): JSX.Element {
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(true);
  // The pulse runs once per answer, not again when the body reopens.
  const [pulsed, setPulsed] = useState(false);
  const {before, after} = traceLines(audit);
  return (
    <motion.section
      className="rounded-lg border border-slate-200 bg-white text-xs shadow-sm"
      aria-label="Answer trace"
      data-testid="trace-drawer"
      variants={pick(traceDrawer.drawer, reduced)}
      initial="hidden"
      animate="visible"
      exit="exit"
    >
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-left text-sm font-medium"
        aria-expanded={open}
        data-testid="trace-toggle"
        onClick={() => setOpen(value => !value)}
      >
        <span>Answer trace</span>
        <span className="text-xs text-slate-500">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <dl
          className="space-y-1 border-t border-slate-200 px-3 py-2 font-mono"
          data-testid="trace-body"
        >
          {rows(before)}
          <motion.div
            className="origin-left py-1 text-sm font-semibold text-accent"
            variants={pick(traceDrawer.pulse, reduced)}
            initial={pulsed ? false : 'hidden'}
            animate="visible"
            onAnimationComplete={() => setPulsed(true)}
            data-testid="model-requests-row"
          >
            <dt className="sr-only">model requests</dt>
            <dd data-testid="model-requests">{requestLine(audit)}</dd>
          </motion.div>
          {rows(after)}
        </dl>
      )}
    </motion.section>
  );
}
