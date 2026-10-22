import type {Page} from '@playwright/test';
import {expect, test} from '@playwright/test';

import {openKeel, stateRoot} from './support/api';

/** The visible text of the answer and the right panel, without request IDs. */
async function content(page: Page): Promise<string> {
  const answer = await page.getByTestId('answer-container').innerText();
  const panel = await page.getByTestId('right-panel').innerText();
  return `${answer}\n${panel}`.replace(/request \S+/g, 'request <id>');
}

/** Elements of the answer and the panel that are mid-animation. */
function moving(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const roots = ['answer-container', 'right-panel', 'trace-drawer'].map(id =>
      document.querySelector(`[data-testid="${id}"]`),
    );
    const found: string[] = [];
    for (const root of roots) {
      for (const el of root?.querySelectorAll<HTMLElement>('*') ?? []) {
        const style = getComputedStyle(el);
        if (
          style.opacity !== '1' ||
          (style.transform !== 'none' && style.transform !== '')
        ) {
          found.push(
            `${el.tagName} ${el.getAttribute('data-testid') ?? ''} ${style.opacity} ${style.transform}`,
          );
        }
      }
    }
    return found;
  });
}

async function askExample2(page: Page): Promise<void> {
  await page.getByTestId('example-chip').nth(1).click();
  await expect(stateRoot(page)).toHaveAttribute('data-state', 'complete');
}

test('test_ui_reduced_motion: the complete state appears at once with the same content', async ({
  page,
}) => {
  await page.emulateMedia({reducedMotion: 'reduce'});
  await openKeel(page);
  await askExample2(page);
  // No element is mid-transition right when the state lands.
  expect(await moving(page)).toEqual([]);
  const badge = page.getByTestId('cost-badge');
  expect(await badge.innerText()).toBe(await badge.getAttribute('data-final'));
  const reduced = await content(page);

  await page.emulateMedia({reducedMotion: 'no-preference'});
  await page.reload();
  await askExample2(page);
  await expect(badge).toHaveText(
    (await badge.getAttribute('data-final')) ?? '',
  );
  await expect.poll(() => moving(page)).toEqual([]);
  expect(await content(page)).toBe(reduced);
});

test('the trace drawer reduced twin: the drawer and the request line land still', async ({
  page,
}) => {
  await page.emulateMedia({reducedMotion: 'reduce'});
  await openKeel(page);
  await askExample2(page);
  const drawer = page.getByTestId('trace-drawer');
  await expect(drawer).toBeVisible();
  // No spring and no pulse: nothing in the drawer moves when it appears.
  expect(await moving(page)).toEqual([]);
  const line = drawer.getByTestId('model-requests');
  await expect(line).toHaveText('model requests: 1');
  const row = drawer.getByTestId('model-requests-row');
  expect(await row.evaluate(el => getComputedStyle(el).transform)).toMatch(
    /^(none|)$/,
  );
});

test('the streamed answer: each block mounts once, and nothing scales the text', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const seen = {removed: 0, scaled: 0, mounted: 0};
    (window as unknown as {keelStream: typeof seen}).keelStream = seen;
    const isBlock = (node: Node): boolean =>
      node instanceof Element &&
      (node.matches('[data-testid="answer-block"]') ||
        node.querySelector('[data-testid="answer-block"]') !== null);
    new MutationObserver(records => {
      for (const record of records) {
        record.addedNodes.forEach(node => {
          seen.mounted += isBlock(node) ? 1 : 0;
        });
        record.removedNodes.forEach(node => {
          seen.removed += isBlock(node) ? 1 : 0;
        });
      }
    }).observe(document, {childList: true, subtree: true});
    const sample = (): void => {
      const box = document.querySelector('[data-testid="answer-container"]');
      const transform = box === null ? 'none' : getComputedStyle(box).transform;
      const match = /^matrix\(([^,]+), [^,]+, [^,]+, ([^,]+),/.exec(transform);
      if (match !== null && (match[1] !== '1' || match[2] !== '1')) {
        seen.scaled += 1;
      }
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
  await openKeel(page);
  await askExample2(page);
  const seen = await page.evaluate(
    () =>
      (
        window as unknown as {
          keelStream: {removed: number; scaled: number; mounted: number};
        }
      ).keelStream,
  );
  expect(seen.mounted).toBeGreaterThan(0);
  expect(seen.removed).toBe(0);
  expect(seen.scaled).toBe(0);
});
