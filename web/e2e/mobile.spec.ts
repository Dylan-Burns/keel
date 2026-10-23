import {devices, expect, test} from '@playwright/test';

import {openKeel, stateRoot} from './support/api';

const phone = devices['Pixel 7'];

test.use({
  viewport: phone.viewport,
  deviceScaleFactor: phone.deviceScaleFactor,
  isMobile: phone.isMobile,
  hasTouch: phone.hasTouch,
  userAgent: phone.userAgent,
});

test('the phone layout: 1 column, the panel as a drawer, every control reachable', async ({
  page,
}) => {
  await openKeel(page);
  const width = page.viewportSize()?.width ?? 0;
  const noSideScroll = (): Promise<boolean> =>
    page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );

  expect(await noSideScroll()).toBe(true);
  await page.getByTestId('example-chip').first().click();
  await expect(stateRoot(page)).toHaveAttribute(
    'data-state',
    /^(complete|partial_coverage)$/,
  );
  expect(await noSideScroll()).toBe(true);

  // 1 column: the answer spans the width; the panel is a closed drawer.
  const answer = await page.getByTestId('answer-area').boundingBox();
  expect(answer?.width ?? 0).toBeGreaterThan(width * 0.8);
  await expect(page.getByTestId('right-panel')).toBeHidden();

  // The Sources button opens the drawer, Close closes it.
  await page.getByTestId('open-sources').click();
  const panel = page.getByTestId('right-panel');
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId('chunk-row').first()).toBeVisible();
  await panel.getByRole('button', {name: 'Close'}).click();
  await expect(panel).toBeHidden();

  // A citation chip opens the filing reader full width over the drawer on
  // the chunk; closing the reader leaves the drawer open on the chunk.
  await page.getByTestId('citation-chip').first().click();
  const reader = page.getByTestId('filing-reader');
  await expect(reader).toBeVisible();
  const readerBox = await reader.boundingBox();
  expect(readerBox?.width ?? 0).toBeGreaterThan(width * 0.95);
  expect(await noSideScroll()).toBe(true);
  await page.getByTestId('reader-close').click();
  await expect(reader).toHaveCount(0);
  await expect(page.getByTestId('selected-chunk')).toBeVisible();
  await panel.getByRole('button', {name: 'Close'}).click();

  // Every control is inside the viewport width and can take a tap.
  for (const name of ['Ask', 'Copy as markdown', 'Export JSON']) {
    const control = page.getByRole('button', {name});
    await control.scrollIntoViewIfNeeded();
    const box = await control.boundingBox();
    expect(box, name).not.toBeNull();
    expect((box?.x ?? 0) + (box?.width ?? 0), name).toBeLessThanOrEqual(width);
  }
  await page.getByRole('button', {name: 'Copy as markdown'}).tap();
});
