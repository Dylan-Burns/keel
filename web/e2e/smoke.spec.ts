import {expect, test} from '@playwright/test';

test('the page has the title and the heading Keel', async ({page}) => {
  await page.goto('/');
  await expect(page).toHaveTitle('Keel');
  await expect(
    page.getByRole('heading', {level: 1, name: 'Keel'}),
  ).toBeVisible();
});
