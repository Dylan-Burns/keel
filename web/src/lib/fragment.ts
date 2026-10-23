/**
 * The deep link of a citation: a URL text fragment (WICG scroll-to-text)
 * on the SEC URL, so the browser lands on the quoted text and highlights
 * it. The same rule as `keel/locations.py`, checked by the same vectors:
 *
 * 1. Drop markdown marks (`*`, `_`, backticks, `#`) and a `TABLE:` tag.
 * 2. A quote with `|` is a table row: each cell is a candidate. Otherwise
 *    the whole quote is the 1 candidate.
 * 3. Split each candidate on whitespace into runs of safe words: letters
 *    and digits only. A word with 1 trailing `,` `.` `;` `:` `?` `!` keeps
 *    its core and ends the run; any other word ends the run and is left
 *    out, because filing HTML may differ in quotes, dashes, and other
 *    punctuation.
 * 4. Prose: the start is the first 6 words of the first run of 4 or more
 *    words, else of the first run of 3 words; the end is the last 4 words
 *    of the last later run of 3 or more words, never overlapping the start.
 *    Table: the start is the anchor (the table title) when given, because
 *    row labels repeat across a filing; else the first 6 words of the
 *    longest cell run of 2 or more words. A table fragment has no end.
 * 5. No run qualifies: the anchor when given, else no fragment and the
 *    plain URL. An anchor is the longest safe run of its text, up to 8
 *    words.
 * 6. Percent-encode every character but letters and digits, including
 *    `-`, `,`, and `&`, and join as `#:~:text=<start>,<end>`.
 */
import type {ChunkLocation} from '../api/types';
import {isSecUrl} from './markdown';

const START_WORDS = 6;
const ANCHOR_WORDS = 8;
const END_WORDS = 4;
const MIN_PROSE_WORDS = 3;
const MIN_CELL_WORDS = 2;

const SAFE = /^[A-Za-z0-9]+$/;
const TRAILING = /^([A-Za-z0-9]+)[,.;:?!]$/;
const MARKS = /[*_`#]+/g;
const TABLE_TAG = /^\s*TABLE:\s*/;

/** The marker of a text directive in a URL. */
export const TEXT_DIRECTIVE = '#:~:text=';

/**
 * Splits a text into runs of safe words (rule step 3).
 *
 * @param text The text.
 * @return The runs, none empty.
 */
function runsOf(text: string): string[][] {
  const runs: string[][] = [];
  let current: string[] = [];
  for (const token of text.split(/\s+/)) {
    if (token === '') {
      continue;
    }
    if (SAFE.test(token)) {
      current.push(token);
      continue;
    }
    const core = TRAILING.exec(token)?.[1];
    if (core !== undefined) {
      current.push(core);
    }
    runs.push(current);
    current = [];
  }
  runs.push(current);
  return runs.filter(run => run.length > 0);
}

/**
 * Percent-encodes a phrase; only letters and digits stay (rule step 6).
 *
 * @param words The words.
 * @return The encoded phrase.
 */
function encode(words: readonly string[]): string {
  return Array.from(words.join(' '))
    .map(c =>
      /[A-Za-z0-9]/.test(c)
        ? c
        : `%${c.charCodeAt(0).toString(16).toUpperCase().padStart(2, '0')}`,
    )
    .join('');
}

/**
 * The longest run, the first on a tie.
 *
 * @param runs The runs.
 * @return The run, or undefined.
 */
function longest(runs: readonly string[][]): string[] | undefined {
  let best: string[] | undefined;
  for (const run of runs) {
    if (best === undefined || run.length > best.length) {
      best = run;
    }
  }
  return best;
}

/**
 * The start and end words of a prose quote (rule step 4).
 *
 * @param text The cleaned quote.
 * @return The words, or null.
 */
function prose(text: string): {start: string[]; end: string[]} | null {
  const runs = runsOf(text).filter(run => run.length >= MIN_PROSE_WORDS);
  if (runs.length === 0) {
    return null;
  }
  const longer = runs.findIndex(run => run.length > MIN_PROSE_WORDS);
  const index = longer === -1 ? 0 : longer;
  const first = runs[index] ?? [];
  const start = first.slice(0, START_WORDS);
  const rest = [first.slice(start.length), ...runs.slice(index + 1)];
  const later = rest.filter(run => run.length >= MIN_PROSE_WORDS);
  const end = later.at(-1)?.slice(-END_WORDS) ?? [];
  return {start, end};
}

/**
 * The words of an anchor: its longest safe run (rule step 5).
 *
 * @param text The anchor, or undefined.
 * @return The words, or undefined.
 */
function anchorWords(text: string | null | undefined): string[] | undefined {
  return longest(runsOf((text ?? '').replace(MARKS, ' ')))?.slice(
    0,
    ANCHOR_WORDS,
  );
}

/**
 * Builds the text directive that scrolls to a quote.
 *
 * @param quote The cited quote, verbatim from the chunk.
 * @param anchor The table title of a table passage: the start of a table
 *     quote, and the fallback of a prose quote with no safe run.
 * @return Such as `:~:text=Start%20words,end%20words`, or null.
 */
export function textFragment(
  quote: string,
  anchor?: string | null,
): string | null {
  const clean = quote.replace(MARKS, ' ').replace(TABLE_TAG, '');
  let start: string[] | undefined;
  let end: string[] = [];
  if (clean.includes('|')) {
    const cells = clean
      .split('|')
      .flatMap(cell => runsOf(cell))
      .filter(run => run.length >= MIN_CELL_WORDS);
    start = anchorWords(anchor) ?? longest(cells)?.slice(0, START_WORDS);
  } else {
    const words = prose(clean);
    start = words?.start;
    end = words?.end ?? [];
  }
  start ??= anchorWords(anchor);
  if (start === undefined || start.length === 0) {
    return null;
  }
  const directive = `:~:text=${encode(start)}`;
  return end.length > 0 ? `${directive},${encode(end)}` : directive;
}

/**
 * Adds the text fragment of a quote to an SEC URL.
 *
 * @param url The trusted SEC URL, or null.
 * @param quote The cited quote.
 * @param anchor The anchor of `textFragment`.
 * @return The URL with `#:~:text=...`, the plain URL when no fragment can
 *     be built or the URL is not on `https://www.sec.gov/`, or null.
 */
export function deepLink(
  url: string | null | undefined,
  quote: string,
  anchor?: string | null,
): string | null {
  if (url === null || url === undefined || url === '') {
    return null;
  }
  if (!isSecUrl(url)) {
    return url;
  }
  const fragment = textFragment(quote, anchor);
  if (fragment === null) {
    return url;
  }
  return `${url.split('#')[0]}#${fragment}`;
}

/**
 * The key of a table row in `row_fragments`: whitespace collapsed.
 *
 * @param row The row.
 * @return The key.
 */
export function rowKey(row: string): string {
  return row.split(/\s+/).filter(Boolean).join(' ');
}

/**
 * The directive of the table row that a quote cites, the same rule as
 * `row_fragment_for` in `keel/locations.py`: an exact row first, then the
 * first row that contains a quote line or that a quote line contains.
 *
 * @param quote The cited quote.
 * @param rows The `row_fragments` of the location.
 * @return The directive, or null.
 */
export function rowFragmentFor(
  quote: string,
  rows: Readonly<Record<string, string>> | null | undefined,
): string | null {
  if (rows === null || rows === undefined) {
    return null;
  }
  const lines = quote
    .split('\n')
    .map(rowKey)
    .filter(line => line !== '');
  for (const line of lines) {
    const exact = rows[line];
    if (exact !== undefined) {
      return exact;
    }
  }
  for (const line of lines) {
    for (const [key, fragment] of Object.entries(rows)) {
      if (key.includes(line) || line.includes(key)) {
        return fragment;
      }
    }
  }
  return null;
}

/**
 * The deep link of a cited passage. A table row with a server-built
 * directive (`row_fragments`) lands on that row; any other table passage
 * anchors on its title.
 *
 * @param url The SEC URL.
 * @param quote The quote, or the passage text.
 * @param location The location of the chunk, when known.
 * @return The deep link, the plain URL, or null.
 */
export function citationLink(
  url: string | null | undefined,
  quote: string,
  location?: ChunkLocation | null,
): string | null {
  const row = rowFragmentFor(quote, location?.row_fragments);
  if (row !== null && url !== null && url !== undefined && isSecUrl(url)) {
    return `${url.split('#')[0]}#${row}`;
  }
  const anchor = location?.is_table === true ? location.anchor : null;
  return deepLink(url, quote, anchor);
}

/**
 * The position of a passage in its item, such as `Passage 3 of 36` or
 * `Table, passage 12 of 84`.
 *
 * @param location The location.
 * @return The position, or an empty string.
 */
export function positionLabel(location: ChunkLocation): string {
  const counted = location.passage > 0 && location.passages > 0;
  const passage = `passage ${location.passage} of ${location.passages}`;
  if (location.is_table) {
    return counted ? `Table, ${passage}` : 'Table';
  }
  return counted ? `Passage ${passage.slice('passage '.length)}` : '';
}

/**
 * The 1-line place of a passage for a text export: the section label, the
 * position, and the accession number.
 *
 * @param location The location, or null.
 * @return Such as `Part I, Item 1A. Risk Factors, passage 3 of 36,
 *     accession 0000320193-25-000079`, or an empty string.
 */
export function describeLocation(
  location: ChunkLocation | null | undefined,
): string {
  if (location === null || location === undefined) {
    return '';
  }
  const parts = [location.section_label];
  const position = positionLabel(location);
  if (position !== '') {
    parts.push(position.toLowerCase());
  }
  if (location.accession !== null) {
    parts.push(`accession ${location.accession}`);
  }
  return parts.join(', ');
}
