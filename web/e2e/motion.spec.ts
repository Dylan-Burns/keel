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
