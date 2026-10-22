import {expect, test} from '@playwright/test';

import {openKeel, stateRoot} from './support/api';

test('the page loads with the coverage of the mini corpus and a green dot', async ({
  page,
}) => {
  await openKeel(page);
  await expect(page).toHaveTitle('Keel');
  await expect(
    page.getByRole('heading', {level: 1, name: 'Keel'}),
  ).toBeVisible();
  await expect(stateRoot(page)).toHaveAttribute('data-state', 'empty');
  await expect(page.getByTestId('coverage-summary')).toContainText(
    '3 companies',
  );
  await expect(page.getByTestId('health-dot')).toHaveAttribute(
    'data-health',
    'green',
  );
  await expect(page.getByTestId('example-chip')).toHaveCount(3);
});

test('without a token the page asks for it', async ({page}) => {
  await openKeel(page, {withToken: false});
  await expect(page.getByLabel('Access token')).toBeVisible();
  await expect(page.getByTestId('coverage-summary')).toContainText(
    'Enter the access token',
  );
});
