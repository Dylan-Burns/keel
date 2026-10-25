/**
 * Reads `eval/report.md` (written by `keel eval`, chapter 18) into data:
 * its sections, their paragraphs, and their tables as rows of named
 * fields. The eval page draws its charts from it, and the JSON download is
 * this structure. Pure functions; no request.
 */
import {splitSections} from '../components/MarkdownDocument';

/** 1 markdown table: its header and its rows of cells. */
export interface ReportTable {
  readonly columns: readonly string[];
  readonly rows: readonly (readonly string[])[];
}

/** 1 section of the report. */
export interface ReportSection {
  readonly heading: string | null;
  readonly level: number;
  /** The paragraphs outside the tables, in order. */
  readonly text: readonly string[];
  readonly tables: readonly ReportTable[];
}

/** The whole report as data. */
export interface ParsedReport {
  /** The run details of the first table (Run ID, models, wall time). */
  readonly run: Readonly<Record<string, string>>;
  readonly sections: readonly ReportSection[];
}

/** The cells of 1 table line, without the outer pipes. */
function cells(line: string): string[] {
  const inner = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return inner.split('|').map(cell => cell.trim());
}

/** True for the `| --- | --- |` line under a table header. */
function isDivider(line: string): boolean {
  return /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(line.trim());
}

/**
 * Splits the body of 1 section into paragraphs and tables.
 *
 * @param body The markdown body.
 * @return The paragraphs and the tables.
 */
export function readBody(body: string): {
  text: string[];
  tables: ReportTable[];
} {
  const text: string[] = [];
  const tables: ReportTable[] = [];
  const lines = body.split('\n');
  let paragraph: string[] = [];
  const flush = (): void => {
    const joined = paragraph.join(' ').trim();
    if (joined !== '') {
      text.push(joined);
    }
    paragraph = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? '';
    const next = lines[i + 1] ?? '';
    if (line.trim().startsWith('|') && isDivider(next)) {
      flush();
      const columns = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && (lines[i] ?? '').trim().startsWith('|')) {
        rows.push(cells(lines[i] ?? ''));
        i++;
      }
      i--;
      tables.push({columns, rows});
    } else if (line.trim() === '') {
      flush();
    } else {
      paragraph.push(line.trim());
    }
  }
  flush();
  return {text, tables};
}

/**
 * Parses the report.
 *
 * @param markdown The report.
 * @return The run details and the sections.
 */
export function parseReport(markdown: string): ParsedReport {
  const sections = splitSections(markdown).map(section => {
    const {text, tables} = readBody(section.body);
    return {heading: section.heading, level: section.level, text, tables};
  });
  const run: Record<string, string> = {};
  const first = sections[0]?.tables[0];
  if (first !== undefined && first.columns[0] === 'Field') {
    for (const [field, value] of first.rows) {
      if (field !== undefined && value !== undefined) {
        run[field] = value;
      }
    }
  }
  return {run, sections};
}

/**
 * The report as a JSON document: the run details, then each section with
 * its paragraphs and its tables as rows of named fields.
 *
 * @param report The parsed report.
 * @return The JSON value.
 */
export function reportJson(report: ParsedReport): unknown {
  return {
    run: report.run,
    sections: report.sections.map(section => ({
      heading: section.heading,
      text: section.text,
      tables: section.tables.map(table =>
        table.rows.map(row =>
          Object.fromEntries(table.columns.map((c, i) => [c, row[i] ?? ''])),
        ),
      ),
    })),
  };
}

/**
 * The first table of the first section whose heading starts with a prefix.
 *
 * @param report The parsed report.
 * @param prefix The heading prefix, case blind.
 * @return The table, or null.
 */
export function tableOf(
  report: ParsedReport,
  prefix: string,
): ReportTable | null {
  const wanted = prefix.toLowerCase();
  const section = report.sections.find(s =>
    (s.heading ?? '').toLowerCase().startsWith(wanted),
  );
  return section?.tables[0] ?? null;
}

/** 1 row of a table read as a named number, for a chart. */
export interface ReportPoint {
  readonly label: string;
  readonly value: number;
}

/**
 * The numeric cells of 1 column, keyed by the first column. A cell that is
 * not a number (`n/a`) is left out.
 *
 * @param table The table.
 * @param column The column name.
 * @return The points in table order.
 */
export function column(table: ReportTable | null, name: string): ReportPoint[] {
  if (table === null) {
    return [];
  }
  const at = table.columns.indexOf(name);
  if (at < 0) {
    return [];
  }
  const points: ReportPoint[] = [];
  for (const row of table.rows) {
    const value = Number.parseFloat(row[at] ?? '');
    const label = row[0] ?? '';
    if (Number.isFinite(value) && label !== '') {
      points.push({label, value});
    }
  }
  return points;
}
