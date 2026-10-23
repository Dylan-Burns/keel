/**
 * Helpers of the filing reader: the table of a table passage and the place
 * of a quote in a passage. The reader renders both as JSX text nodes.
 */

/** A table passage split into its caption, header, and rows. */
export interface ReaderTableData {
  readonly caption: string;
  readonly units: string;
  readonly columns: readonly string[];
  readonly rows: readonly (readonly string[])[];
}

/**
 * Parses a table passage of the chunker: `TABLE: <title> | units: <u> |
 * columns: <a> | <b>` on the first line, then 1 row per line with cells
 * split by ` | `. A line with no ` | ` is a 1-cell row.
 *
 * @param text The passage text.
 * @return The table, or null when the text is not a table passage.
 */
export function parseTable(text: string): ReaderTableData | null {
  const [first = '', ...lines] = text.split('\n');
  if (!first.startsWith('TABLE:')) {
    return null;
  }
  const parts = first.slice('TABLE:'.length).split(' | ');
  let caption = (parts[0] ?? '').trim();
  let units = '';
  const columns: string[] = [];
  let inColumns = false;
  for (const part of parts.slice(1)) {
    if (part.startsWith('units:')) {
      units = part.slice('units:'.length).trim();
    } else if (part.startsWith('columns:')) {
      inColumns = true;
      columns.push(part.slice('columns:'.length).trim());
    } else if (inColumns) {
      columns.push(part.trim());
    } else {
      caption = `${caption} | ${part}`.trim();
    }
  }
  if (caption.startsWith('|')) {
    caption = caption.slice(1).trim();
  }
  const rows = lines
    .filter(line => line.trim() !== '')
    .map(line => line.split(' | ').map(cell => cell.trim()));
  return {caption, units, columns, rows};
}

/** The place of a quote in a text: the text before, the quote, after. */
export interface QuoteSplit {
  readonly before: string;
  readonly match: string;
  readonly after: string;
}

/**
 * Escapes a text for a regular expression.
 *
 * @param text The text.
 * @return The escaped text.
 */
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Finds a quote in a passage: verbatim first, then with any run of
 * whitespace matching any other, as the passage may wrap lines.
 *
 * @param text The passage text.
 * @param quote The quote.
 * @return The split, or null when the quote is not in the text.
 */
export function splitQuote(text: string, quote: string): QuoteSplit | null {
  const needle = quote.trim();
  if (needle === '') {
    return null;
  }
  const at = text.indexOf(needle);
  if (at !== -1) {
    return {
      before: text.slice(0, at),
      match: needle,
      after: text.slice(at + needle.length),
    };
  }
  const words = needle.split(/\s+/).map(escapeRegExp);
  const found = new RegExp(words.join('\\s+')).exec(text);
  if (found === null) {
    return null;
  }
  return {
    before: text.slice(0, found.index),
    match: found[0],
    after: text.slice(found.index + found[0].length),
  };
}

/**
 * True when a table row is the row a quote cites: the quote holds the row
 * or the row holds the quote, compared with the cells joined by ` | `.
 *
 * @param row The row cells.
 * @param quote The quote, if any.
 * @return Whether the row is cited.
 */
export function isCitedRow(
  row: readonly string[],
  quote: string | undefined,
): boolean {
  if (quote === undefined || quote.trim() === '') {
    return false;
  }
  const joined = row.join(' | ').trim();
  const needle = quote.trim();
  return joined !== '' && (needle.includes(joined) || joined.includes(needle));
}
