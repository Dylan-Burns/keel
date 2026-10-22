import {expect, test} from '@playwright/test';

import {isLive, openKeel} from './support/api';

// The admin jobs that change the served index: keel add and keel restore
// through the web UI. They run in the ops-jobs project of
// playwright.config.ts, after every other spec, so the coverage the other
// specs check stays the mini corpus. Serial: 1 heavy job at a time.
test.describe.configure({mode: 'serial'});

test('adding a ticker runs the add job to succeeded', async ({page}) => {
  test.skip(!isLive, 'the add job needs keel serve');
  test.setTimeout(240_000);
  await openKeel(page, {path: '/companies'});
  await page.getByTestId('add-ticker').fill('zts');
  await page.getByTestId('add-submit').click();
  const card = page.getByTestId('job-card');
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute('data-status', 'succeeded', {
    timeout: 180_000,
  });
  await expect(card.getByTestId('job-result')).toContainText('ZTS');
  await expect(card.getByTestId('job-phase')).toHaveText('done');
  // The job page shows the same job.
  await card.getByRole('link', {name: 'Open job'}).click();
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f]{16}$/);
  await expect(page.getByTestId('job-card')).toHaveAttribute(
    'data-status',
    'succeeded',
  );
});

test('a restore needs the exact archive name typed', async ({page}) => {
  test.skip(!isLive, 'the backup and restore jobs need keel serve');
  test.setTimeout(240_000);
  await openKeel(page, {path: '/system'});
  const backups = page.getByTestId('sys-backups');
  await backups.getByTestId('backup-now').click();
  await expect(backups.getByTestId('job-card')).toHaveAttribute(
    'data-status',
    'succeeded',
    {timeout: 120_000},
  );
  // The page reloads the listing when the job ends.
  const row = backups.getByTestId('backup-row').first();
  await expect(row).toBeVisible();
  const name = (await row.getAttribute('data-name')) ?? '';
  expect(name).toMatch(/^keel-.+\.tar\.gz$/);

  await row.getByTestId('backup-restore').click();
  const confirm = page.getByTestId('restore-confirm');
  const input = confirm.getByTestId('restore-confirm-input');
  const submit = confirm.getByTestId('restore-confirm-submit');
  await expect(input).toBeFocused();
  await expect(submit).toBeDisabled();
  await input.fill(name.slice(0, -3));
  await expect(submit).toBeDisabled();
  await input.fill(name.toUpperCase());
  await expect(submit).toBeDisabled();
  await input.fill(name);
  await expect(submit).toBeEnabled();
  await submit.click();
  const job = page
    .getByTestId('sys-backups')
    .locator('[data-testid="job-card"]');
  await expect(job).toHaveAttribute('data-status', 'succeeded', {
    timeout: 180_000,
  });
  await expect(job.getByTestId('job-result')).toContainText('index version');
});
