/**
 * Copy as markdown and Export JSON for the footer (chapter 14.5). A copy
 * during the stream carries a header line that says partial answer with the
 * request ID (E-F-05).
 */
import type {Run} from '../state';
import {answerText} from '../state';

/**
 * The header line of a partial copy.
 *
 * @param requestId The request ID.
 * @return The line.
 */
export function partialHeader(requestId: string): string {
  return `> Partial answer, still streaming (request ${requestId})`;
}

/**
 * Builds the markdown of an answer.
 *
 * @param run The run to copy.
 * @return The markdown text; partial when the run has no final answer.
 */
export function answerToMarkdown(run: Run): string {
  const lines: string[] = [];
  const requestId = run.meta?.request_id ?? run.requestId;
  if (run.final === null) {
    lines.push(partialHeader(requestId), '');
  }
  lines.push(`# ${run.question}`, '', answerText(run), '');
  for (const company of run.findings) {
    lines.push(`## ${company.company} (${company.ticker})`, '');
    for (const finding of company.findings) {
      const mark = finding.unverified === true ? ' (unverified)' : '';
      const cites = finding.citations.map(id => `[${id}]`).join(' ');
      lines.push(`- ${finding.point}${mark} ${cites}`.trimEnd());
    }
    lines.push('');
  }
  const table = run.final?.answer.comparison_table ?? null;
  if (table !== null) {
    lines.push(`| ${table.columns.join(' | ')} |`);
    lines.push(`| ${table.columns.map(() => '---').join(' | ')} |`);
    for (const row of table.rows) {
      lines.push(`| ${row.join(' | ')} |`);
    }
    lines.push('');
  }
  const gaps = run.final?.answer.gaps ?? [];
  if (gaps.length > 0) {
    lines.push('## Gaps', '', ...gaps.map(gap => `- ${gap}`), '');
  }
  const cited = run.final?.citations_resolved ?? [];
  if (cited.length > 0) {
    lines.push('## Sources', '');
    for (const c of cited) {
      const url = c.sec_url === null ? '' : ` ${c.sec_url}`;
      lines.push(
        `- [${c.chunk_id}] ${c.filing_name}, ${c.section_title}${url}`,
      );
    }
    lines.push('');
  }
  lines.push(`Request ${requestId}`);
  return lines.join('\n');
}

/**
 * The JSON export of a run: the final response, or the parts received.
 *
 * @param run The run.
 * @return Pretty JSON.
 */
export function answerToJson(run: Run): string {
  if (run.final !== null) {
    return JSON.stringify(run.final, null, 2);
  }
  return JSON.stringify(
    {
      partial: true,
      request_id: run.meta?.request_id ?? run.requestId,
      analysis: run.analysis,
      retrieval: run.retrieval,
      direct_answer: answerText(run),
      company_findings: run.findings,
    },
    null,
    2,
  );
}
