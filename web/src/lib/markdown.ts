/**
 * The answer markdown renderer: `marked` then DOMPurify with the allow list
 * of chapter 15 (control S-03). Only `https://www.sec.gov` links keep their
 * `href`; every other link becomes plain text. The result is the only HTML
 * the page renders through `dangerouslySetInnerHTML` (in AnswerMarkdown).
 */
import DOMPurify from 'dompurify';
import {marked} from 'marked';

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
 * Renders answer markdown to sanitized HTML.
 *
 * @param markdown The model text.
 * @return HTML with only the allowed tags and SEC links.
 */
export function renderMarkdown(markdown: string): string {
  installHook();
  const html = marked.parse(markdown, {async: false, gfm: true});
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [...ALLOWED_TAGS],
    ALLOWED_ATTR: [...ALLOWED_ATTR],
    ALLOW_DATA_ATTR: false,
  });
}
