import {expect, test} from '@playwright/test';

import {openKeel, stateRoot} from './support/api';

test('a citation chip opens the filing reader with the passage highlighted and in view', async ({
  page,
}) => {
  await openKeel(page);
  await page.getByTestId('example-chip').first().click();
  await expect(stateRoot(page)).toHaveAttribute(
    'data-state',
    /^(complete|partial_coverage)$/,
  );
  const chip = page.getByTestId('citation-chip').first();
  await expect(chip).toBeEnabled();
  const chunkId = await chip.getAttribute('data-chunk-id');
  await chip.click();

  const reader = page.getByTestId('filing-reader');
  await expect(reader).toBeVisible();
  await expect(reader).toHaveAttribute('data-chunk-id', chunkId ?? '');
  await expect(reader).toHaveAttribute('data-loaded', 'true');
  const cited = reader.locator(
    '[data-testid="reader-passage"][data-cited="true"]',
  );
  await expect(cited).toHaveCount(1);
  const mark = cited.getByTestId('reader-mark').first();
  await expect(mark).toBeVisible();
  await expect(mark).toBeInViewport();
  await expect(page.getByTestId('reader-header')).toContainText('Filed');

  // Escape closes the reader; the Sources panel opens it again.
  await page.keyboard.press('Escape');
  await expect(reader).toHaveCount(0);
  const sources = page.getByTestId('open-sources');
  if (await sources.isVisible()) {
    await sources.click();
  }
  await page.getByTestId('view-in-filing').first().click();
  await expect(page.getByTestId('filing-reader')).toBeVisible();
  await expect(
    page.getByTestId('filing-reader').getByTestId('reader-mark').first(),
  ).toBeInViewport();
});
