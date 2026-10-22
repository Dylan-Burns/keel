/**
 * The answer markdown renderer: `marked` then DOMPurify with the allow list
 * of chapter 15 (control S-03). Only `https://www.sec.gov` links keep their
 * `href`; every other link becomes plain text. The result is the only HTML
 * the page renders through `dangerouslySetInnerHTML` (in AnswerMarkdown).
 */
import DOMPurify from 'dompurify';
import {Marked} from 'marked';

import {isCitationId} from './citations';

/** The tags of the chapter 15 allow list. */
export const ALLOWED_TAGS: readonly string[] = [
  'p',
  'strong',
  'em',
  'ul',
  'ol',
  'li',
  'table',
  'thead',
  'tbody',
  'tr',
  'th',
  'td',
  'code',
  'a',
];

/** The 1 attribute the allow list keeps (on `a` only, and SEC only). */
export const ALLOWED_ATTR: readonly string[] = ['href'];

/**
 * True for a URL that may render as a link: https on the host www.sec.gov,
 * with no credentials and no port.
 *
 * @param url The URL text.
 * @return Whether the URL is an SEC link.
 */
export function isSecUrl(url: string | null | undefined): url is string {
  if (url === null || url === undefined) {
    return false;
  }
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  return (
    parsed.protocol === 'https:' &&
    parsed.hostname === 'www.sec.gov' &&
    parsed.port === '' &&
    parsed.username === '' &&
    parsed.password === ''
  );
}

let hooked = false;

function installHook(): void {
  if (hooked) {
    return;
  }
  hooked = true;
  DOMPurify.addHook('afterSanitizeAttributes', node => {
    if (node.nodeName !== 'A') {
      return;
    }
    const href = node.getAttribute('href');
    if (isSecUrl(href)) {
      node.setAttribute('target', '_blank');
      node.setAttribute('rel', 'noopener noreferrer');
    } else {
      node.removeAttribute('href');
    }
  });
}

/**
 * Escapes the HTML special characters of a text.
 *
 * @param text The text.
 * @return The escaped text.
 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * A private marked instance: raw HTML in the model text renders as escaped
 * text, so a `<script>` shows as text instead of being parsed (E-F-06).
 */
const markdownParser = new Marked({
  async: false,
  gfm: true,
  renderer: {
    html({text}): string {
      return escapeHtml(text);
    },
  },
});

/**
 * Sanitizes HTML with the chapter 15 allow list: only the allowed tags, the
 * `href` attribute, and links to https://www.sec.gov.
 *
 * @param html Untrusted HTML.
 * @return The sanitized HTML.
 */
export function sanitizeHtml(html: string): string {
  installHook();
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [...ALLOWED_TAGS],
    ALLOWED_ATTR: [...ALLOWED_ATTR],
    ALLOW_DATA_ATTR: false,
  });
}

/**
 * Renders answer markdown to sanitized HTML. Raw HTML in the markdown shows
 * as text; DOMPurify then runs on the whole result as a second layer.
 *
 * @param markdown The model text.
 * @return HTML with only the allowed tags and SEC links.
 */
export function renderMarkdown(markdown: string): string {
  return sanitizeHtml(markdownParser.parse(markdown, {async: false}));
}

/** 1 chunk ID or fact ID, as the model cites it inline. */
const ID =
  '(?:facts:[A-Z0-9][A-Z0-9.-]*:[A-Za-z][A-Za-z0-9_]*:(?:Q[1-4])?FY\\d{4}' +
  '|[A-Z0-9][A-Z0-9.-]*_10[KQ]_\\d{4}-\\d{2}-\\d{2}__[a-z_]+__\\d{4,})';

/**
 * A bracket of 1 or more IDs: `[A]` or `[A, B]`. A bracket that opens a
 * markdown link (`[A](url)`) stays as the model wrote it.
 */
const INLINE_CITATION = new RegExp(
  `\\[(${ID}(?:\\s*[,;]\\s*${ID})*)\\](?!\\()`,
  'g',
);

/**
 * An ID bracket the stream has not closed yet, at the end of the text: a
 * ticker or `facts` prefix, so a link or a note in brackets still shows.
 */
const PARTIAL_CITATION =
  /\[(?:f(?:a(?:c(?:t(?:s(?::[^\]\n]{0,200})?)?)?)?)?|[A-Z0-9][A-Z0-9.-]{0,20}(?:_[^\]\n]{0,200})?)$/;

/**
 * Marks the IDs that the answer cites inline as code spans, 1 per ID, so
 * `chipCitations` can turn each into a citation chip after sanitizing.
 * Display only: the copy and the export keep the model text.
 *
 * @param markdown The model text.
 * @return The markdown with each inline ID as a code span.
 */
export function tagCitations(markdown: string): string {
  return markdown.replace(INLINE_CITATION, (_match, ids: string) =>
    ids
      .split(/[,;]/)
      .map(id => `\`${id.trim()}\``)
      .join(' '),
  );
}

/**
 * Drops an ID bracket that is still streaming at the end of the text, so a
 * half ID never flashes before its chip renders.
 *
 * @param markdown The streamed text so far.
 * @return The text without the open bracket at its end.
 */
export function trimPartialCitation(markdown: string): string {
  return markdown.replace(PARTIAL_CITATION, '');
}

/** What the chip of 1 inline citation shows. */
export interface CitationChipView {
  /** The short label, such as `AAPL FY2025`. */
  readonly label: string;
  /** The full source, such as `Apple Inc. 10-K FY2025, Risk Factors`. */
  readonly source: string;
  /** False for a citation the validator removed. */
  readonly valid: boolean;
}

/**
 * Replaces each code span that holds a whole citation ID with a compact
 * chip. Runs on sanitized HTML inside an inert template, and builds every
 * chip with `createElement`, `textContent`, and `setAttribute`, so no text
 * of the model or of the filing is ever parsed as HTML.
 *
 * @param html HTML from `renderMarkdown`.
 * @param resolve The chip of an ID; undefined leaves the code span.
 * @param clickable False until the `final` event: chips are disabled then.
 * @return The HTML with the chips.
 */
export function chipCitations(
  html: string,
  resolve: (chunkId: string) => CitationChipView | undefined,
  clickable: boolean,
): string {
  const template = document.createElement('template');
  template.innerHTML = html;
  for (const code of Array.from(template.content.querySelectorAll('code'))) {
    const chunkId = code.textContent ?? '';
    const view = isCitationId(chunkId) ? resolve(chunkId) : undefined;
    if (view === undefined) {
      continue;
    }
    code.replaceWith(chipElement(chunkId, view, clickable));
  }
  collapseRepeats(template.content);
  return template.innerHTML;
}

/**
 * Folds a chip into the chip just before it (blank space between them
 * only) when both name the same source: `AAPL FY2025 x2`. The folded chip
 * opens the first passage; the sources panel lists every passage.
 *
 * @param root The fragment that holds the chips.
 */
function collapseRepeats(root: DocumentFragment): void {
  for (const chip of Array.from(root.querySelectorAll('button.cite-chip'))) {
    let previous = chip.previousSibling;
    const gap: ChildNode[] = [];
    while (
      previous !== null &&
      previous.nodeType === Node.TEXT_NODE &&
      (previous.textContent ?? '').trim() === ''
    ) {
      gap.push(previous);
      previous = previous.previousSibling;
    }
    if (
      !(previous instanceof HTMLButtonElement) ||
      !previous.classList.contains('cite-chip') ||
      previous.title !== chip.getAttribute('title') ||
      previous.getAttribute('data-label') !== chip.getAttribute('data-label')
    ) {
      continue;
    }
    const count = Number(previous.getAttribute('data-count') ?? '1') + 1;
    const label = previous.getAttribute('data-label') ?? '';
    previous.setAttribute('data-count', String(count));
    previous.textContent = `${label} x${count}`;
    previous.setAttribute(
      'aria-label',
      `${label}, ${count} passages, opens the first: ${previous.title}`,
    );
    for (const node of gap) {
      node.remove();
    }
    chip.remove();
  }
}

/**
 * Builds 1 chip: a button that opens the source, or a warning tag for a
 * citation the validator removed.
 *
 * @param chunkId The cited ID.
 * @param view What the chip shows.
 * @param clickable Whether the button is enabled.
 * @return The chip element.
 */
function chipElement(
  chunkId: string,
  view: CitationChipView,
  clickable: boolean,
): HTMLElement {
  if (!view.valid) {
    const tag = document.createElement('span');
    tag.className = 'tag tag-warn cite-chip';
    tag.setAttribute('data-testid', 'inline-citation-unverified');
    tag.setAttribute('title', `${view.source} (unverified)`);
    tag.textContent = `${view.label} unverified`;
    const note = document.createElement('span');
    note.className = 'sr-only';
    note.textContent = `: ${view.source}`;
    tag.append(note);
    return tag;
  }
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'tag tag-accent cite-chip';
  button.setAttribute('data-testid', 'inline-citation');
  button.setAttribute('data-chunk-id', chunkId);
  button.setAttribute('data-label', view.label);
  button.setAttribute('aria-label', `${view.label}: ${view.source}`);
  button.setAttribute('title', view.source);
  button.disabled = !clickable;
  button.textContent = view.label;
  return button;
}

/**
 * Splits answer markdown into its top-level blocks (paragraphs, lists,
 * tables, headings) as the `marked` lexer reads them. The answer area renders
 * 1 element per block, so a block that is complete keeps its DOM node while
 * later text streams into the last block.
 *
 * @param markdown The model text, complete or still streaming.
 * @return The source text of each block, blank space dropped.
 */
export function markdownBlocks(markdown: string): string[] {
  return markdownParser
    .lexer(markdown)
    .filter(token => token.type !== 'space' && token.raw.trim() !== '')
    .map(token => token.raw);
}
