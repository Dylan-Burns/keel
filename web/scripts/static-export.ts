/**
 * The demo fallbacks of chapter 16.12, step 4: the static HTML export of the
 * 3 example answers and a draft video recording of a full run.
 *
 * Run it against a `keel serve` that answers from the warm cache
 * (`KEEL_OFFLINE=1`), so no question makes a model request:
 *
 *   KEEL_API_TOKEN=... node scripts/static-export.ts http://127.0.0.1:8000
 *   KEEL_API_TOKEN=... node scripts/static-export.ts URL --record FILE.webm
 *
 * The page reads the token from the session storage of the headless browser.
 * The script never writes the token, a request header, or the storage to a
 * file: each export is the rendered answer with the scripts removed, the
 * built CSS inlined, and every link outside https://www.sec.gov dropped.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as process from 'node:process';
import * as url from 'node:url';

import type {Browser, Page} from '@playwright/test';
import {chromium} from '@playwright/test';

/** The example questions, in the order of the chips (src/lib/examples.ts). */
const EXAMPLE_COUNT = 3;

/** The states that end an answer on the page. */
const DONE_STATES = /^(complete|partial_coverage)$/;

/** The longest wait for an answer, in milliseconds. */
const ANSWER_TIMEOUT_MS = 180_000;

/** The size of the recorded video and of the page. */
const VIEWPORT = {width: 1280, height: 800};

/** The repository root, 2 levels above this file. */
const REPO_ROOT = path.resolve(
  path.dirname(url.fileURLToPath(import.meta.url)),
  '..',
  '..',
);

/** The command line of a run. */
interface Options {
  readonly baseUrl: string;
  readonly outDir: string;
  readonly recordTo: string | null;
}

/** One exported answer, for the index page. */
interface Exported {
  readonly file: string;
  readonly question: string;
  readonly state: string;
  readonly requestLine: string;
}

/**
 * Reads the command line.
 *
 * @param argv The arguments after the script name.
 * @return The options of the run.
 */
function parseArgs(argv: string[]): Options {
  let baseUrl = 'http://127.0.0.1:8000';
  let outDir = path.join(REPO_ROOT, 'demo', 'static');
  let recordTo: string | null = null;
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i] ?? '';
    if (arg === '--out') {
      outDir = path.resolve(argv[++i] ?? outDir);
    } else if (arg === '--record') {
      recordTo = path.resolve(argv[++i] ?? 'recording.webm');
    } else {
      baseUrl = arg;
    }
  }
  return {baseUrl: baseUrl.replace(/\/+$/, ''), outDir, recordTo};
}

/**
 * Opens the page with the token in the session storage of the browser.
 *
 * @param page The Playwright page.
 * @param baseUrl The address of `keel serve`.
 * @param token The bearer token of the API.
 */
async function openKeel(
  page: Page,
  baseUrl: string,
  token: string,
): Promise<void> {
  await page.addInitScript(value => {
    window.sessionStorage.setItem('keel.token', value);
  }, token);
  await page.goto(`${baseUrl}/`);
  await page.getByTestId('example-chip').first().waitFor();
}

/**
 * Clicks an example chip and waits for the end of the answer.
 *
 * @param page The Playwright page.
 * @param index The chip, from 0.
 * @return The final state and the request line of the trace drawer.
 */
async function askExample(
  page: Page,
  index: number,
): Promise<{state: string; requestLine: string}> {
  await page.getByTestId('example-chip').nth(index).click();
  const root = page.locator('[data-state]').first();
  await page.waitForFunction(
    pattern => {
      const el = document.querySelector('[data-state]');
      return new RegExp(pattern).test(el?.getAttribute('data-state') ?? '');
    },
    DONE_STATES.source,
    {timeout: ANSWER_TIMEOUT_MS},
  );
  const requests = page.getByTestId('model-requests');
  await requests.waitFor();
  // Let the motion presets settle so the inline styles hold the end values.
  await page.waitForTimeout(1500);
  return {
    state: (await root.getAttribute('data-state')) ?? '',
    requestLine: (await requests.textContent()) ?? '',
  };
}

/**
 * Serializes the rendered page as a self-contained static file: no script,
 * the CSS inlined, and only https://www.sec.gov or relative links.
 *
 * @param page The Playwright page in the answer state.
 * @param css The text of the built stylesheets.
 * @param banner The note at the top of the export.
 * @return The HTML document.
 */
async function snapshot(
  page: Page,
  css: string,
  banner: string,
): Promise<string> {
  const body = await page.evaluate(
    ([styleText, note]) => {
      const doc = document.documentElement.cloneNode(true) as HTMLElement;
      const drop = 'script, noscript, link, iframe, object, embed, template';
      for (const el of Array.from(doc.querySelectorAll(drop))) {
        el.remove();
      }
      for (const el of Array.from(doc.querySelectorAll('*'))) {
        for (const attr of Array.from(el.attributes)) {
          const name = attr.name.toLowerCase();
          const value = attr.value.trim();
          if (name.startsWith('on') || name === 'srcdoc') {
            el.removeAttribute(attr.name);
          } else if (['href', 'src', 'action', 'formaction'].includes(name)) {
            if (!value.startsWith('https://www.sec.gov/')) {
              el.removeAttribute(attr.name);
            }
          }
        }
        if (el instanceof HTMLTextAreaElement) {
          // The value of a text box is not an attribute: keep the question.
          const live = document.querySelector('textarea');
          el.textContent = live?.value ?? '';
        }
        if (el instanceof HTMLButtonElement || el instanceof HTMLInputElement) {
          el.setAttribute('disabled', '');
        }
        if (el instanceof HTMLTextAreaElement) {
          el.setAttribute('readonly', '');
        }
      }
      const head = doc.querySelector('head');
      const style = document.createElement('style');
      style.textContent = styleText;
      head?.appendChild(style);
      const notice = document.createElement('p');
      notice.setAttribute(
        'style',
        'margin:0;padding:8px 16px;font:14px system-ui,sans-serif;' +
          'background:#fef3c7;color:#78350f;border-bottom:1px solid #f59e0b',
      );
      notice.textContent = note;
      const back = document.createElement('a');
      back.setAttribute('href', 'index.html');
      back.setAttribute('style', 'margin-left:12px;color:#78350f');
      back.textContent = 'All 3 answers';
      notice.appendChild(back);
      doc.querySelector('body')?.prepend(notice);
      return doc.outerHTML;
    },
    [css, banner] as const,
  );
  // No trailing spaces, so the files pass the whitespace hook as written.
  return `<!doctype html>\n${body.replace(/[ \t]+$/gm, '')}\n`;
}

/**
 * Reads the text of every stylesheet the page links.
 *
 * @param page The Playwright page.
 * @return The CSS, in link order.
 */
async function builtCss(page: Page): Promise<string> {
  const hrefs = await page.evaluate(() =>
    Array.from(document.querySelectorAll('link[rel="stylesheet"]')).map(
      link => (link as HTMLLinkElement).href,
    ),
  );
  const parts: string[] = [];
  for (const href of hrefs) {
    const response = await page.request.get(href);
    parts.push(await response.text());
  }
  return parts.join('\n');
}

/**
 * Escapes a text for HTML.
 *
 * @param text The text.
 * @return The escaped text.
 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Writes the index page that links the exported answers.
 *
 * @param outDir The export directory.
 * @param answers The exported answers.
 * @param stamp The export date.
 */
function writeIndex(outDir: string, answers: Exported[], stamp: string): void {
  const items = answers
    .map(
      a =>
        `<li><a href="${a.file}">${escapeHtml(a.question)}</a>` +
        `<br><small>${escapeHtml(a.state)}, ${escapeHtml(a.requestLine)}` +
        '</small></li>',
    )
    .join('\n');
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Keel: the 3 example answers</title>
<style>
body{font:16px/1.5 system-ui,sans-serif;max-width:760px;margin:32px auto;padding:0 16px;color:#0f172a}
li{margin:12px 0}small{color:#475569}
</style>
</head>
<body>
<h1>Keel: the 3 example answers</h1>
<p>The static fallback of chapter 16.12, step 4: each page is the answer as the
browser rendered it, with no script and no network request. Exported ${escapeHtml(stamp)}
from the answer cache. The SEC links open the filings on www.sec.gov.</p>
<ol>
${items}
</ol>
</body>
</html>
`;
  fs.writeFileSync(path.join(outDir, 'index.html'), html);
}

/**
 * Exports the 3 example answers as static HTML files.
 *
 * @param browser The browser.
 * @param options The options of the run.
 * @param token The bearer token of the API.
 */
async function exportAnswers(
  browser: Browser,
  options: Options,
  token: string,
): Promise<void> {
  fs.mkdirSync(options.outDir, {recursive: true});
  const stamp = new Date().toISOString().slice(0, 10);
  const answers: Exported[] = [];
  for (let i = 0; i < EXAMPLE_COUNT; i++) {
    const context = await browser.newContext({viewport: VIEWPORT});
    const page = await context.newPage();
    await openKeel(page, options.baseUrl, token);
    const question =
      (await page.getByTestId('example-chip').nth(i).getAttribute('title')) ??
      (await page.getByTestId('example-chip').nth(i).textContent()) ??
      '';
    const {state, requestLine} = await askExample(page, i);
    const asked = await page.locator('textarea').first().inputValue();
    const css = await builtCss(page);
    const banner =
      `Static export of example question ${i + 1}, ${stamp}, ` +
      `served from the Keel answer cache (${requestLine}).`;
    const html = await snapshot(page, css, banner);
    const file = `answer-${i + 1}.html`;
    fs.writeFileSync(path.join(options.outDir, file), html);
    answers.push({file, question: asked || question, state, requestLine});
    console.log(`${file}: ${state}, ${requestLine}, ${html.length} bytes`);
    await context.close();
  }
  writeIndex(options.outDir, answers, stamp);
}

/**
 * Records a full run of the 3 example questions, with the trace drawer
 * closed and opened once on the first answer.
 *
 * @param browser The browser.
 * @param options The options of the run.
 * @param token The bearer token of the API.
 * @param target The video file to write.
 */
async function recordRun(
  browser: Browser,
  options: Options,
  token: string,
  target: string,
): Promise<void> {
  const videoDir = fs.mkdtempSync(path.join(path.dirname(target), '.video-'));
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: {dir: videoDir, size: VIEWPORT},
  });
  const page = await context.newPage();
  await openKeel(page, options.baseUrl, token);
  await page.waitForTimeout(2000);
  for (let i = 0; i < EXAMPLE_COUNT; i++) {
    if (i > 0) {
      await page.goto(`${options.baseUrl}/`);
      await page.getByTestId('example-chip').first().waitFor();
      await page.waitForTimeout(1500);
    }
    const {requestLine} = await askExample(page, i);
    console.log(`recorded question ${i + 1}: ${requestLine}`);
    await page.waitForTimeout(3000);
    const chip = page.getByTestId('citation-chip').first();
    if ((await chip.count()) > 0 && (await chip.isEnabled())) {
      await chip.click();
      await page.waitForTimeout(2500);
    }
    if (i === 0) {
      const toggle = page.getByTestId('trace-toggle');
      await toggle.scrollIntoViewIfNeeded();
      await toggle.click();
      await page.waitForTimeout(1000);
      await toggle.click();
      await page.getByTestId('model-requests').waitFor();
      await page.waitForTimeout(4000);
    }
    await page.mouse.wheel(0, 600);
    await page.waitForTimeout(2500);
  }
  const video = page.video();
  await context.close();
  if (video !== null) {
    await video.saveAs(target);
    await video.delete();
  }
  fs.rmSync(videoDir, {recursive: true, force: true});
  console.log(`recording: ${target}`);
}

/** Runs the export, or the recording with `--record`. */
async function main(): Promise<void> {
  const options = parseArgs(process.argv.slice(2));
  const token = process.env['KEEL_API_TOKEN'] ?? '';
  if (token === '') {
    throw new Error('set KEEL_API_TOKEN to the token of the running server');
  }
  const browser = await chromium.launch();
  try {
    if (options.recordTo === null) {
      await exportAnswers(browser, options, token);
    } else {
      await recordRun(browser, options, token, options.recordTo);
    }
  } finally {
    await browser.close();
  }
}

await main();
