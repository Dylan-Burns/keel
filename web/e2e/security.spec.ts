import {expect, test} from '@playwright/test';

import {UNTRUSTED_URL, openKeel, stateRoot} from './support/api';

test('test_ui_escapes_model_text: a script in the answer renders as text', async ({
  page,
}) => {
  const dialogs: string[] = [];
  page.on('dialog', dialog => {
    dialogs.push(dialog.message());
    void dialog.dismiss();
  });
  await openKeel(page, {fault: 'script_injection', paceMs: 0});
  await page.getByTestId('example-chip').nth(1).click();
  await expect(stateRoot(page)).toHaveAttribute(
    'data-state',
    /^(complete|partial_coverage)$/,
  );

  const answer = page.getByTestId('answer-markdown');
  await expect(answer).toContainText('<script>');
  expect(await answer.locator('script, img, iframe').count()).toBe(0);
  expect(await page.locator('main script').count()).toBe(0);
  const pwned = await page.evaluate(
    () => (window as unknown as {keelPwned?: boolean}).keelPwned,
  );
  expect(pwned).toBeUndefined();
  expect(dialogs).toEqual([]);

  // Every link on the page goes to https://www.sec.gov and opens a new tab.
  await expect(page.locator('a[href]').first()).toBeAttached();
  for (const link of await page.locator('a[href]').all()) {
    const href = (await link.getAttribute('href')) ?? '';
    expect(href.startsWith('https://www.sec.gov/'), href).toBe(true);
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  }
});

test('test_ui_escapes_model_text: a chunk URL outside www.sec.gov renders as text', async ({
  page,
}) => {
  await openKeel(page, {fault: 'script_injection', paceMs: 0});
  await page.getByTestId('example-chip').nth(1).click();
  await expect(stateRoot(page)).toHaveAttribute(
    'data-state',
    /^(complete|partial_coverage)$/,
  );
  const panel = page.getByTestId('right-panel');
  await expect(panel.getByTestId('untrusted-url').first()).toHaveText(
    UNTRUSTED_URL,
  );
  expect(await page.locator(`a[href="${UNTRUSTED_URL}"]`).count()).toBe(0);
});
