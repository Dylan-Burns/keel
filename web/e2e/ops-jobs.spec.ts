import {expect, test} from '@playwright/test';

import {isLive, openKeel} from './support/api';

// The admin jobs that change the served index: keel add and keel restore
// through the web UI. They run in the ops-jobs project of
// playwright.config.ts, after every other spec, so the coverage the other
// specs check stays the mini corpus. Serial: 1 heavy job at a time.
test.describe.configure({mode: 'serial'});

/** The steps of an add job that indexes its filings, in plan order. */
const ADD_STEPS = [
  'corpus',
  'resolve',
  'filings',
  'download_10k',
  'download_10q',
  'convert',
  'parse',
  'chunk',
  'embed',
  'store',
  'publish',
  'reload',
];

test('adding a ticker turns its steps to checks in order', async ({page}) => {
  test.skip(!isLive, 'the add job needs keel serve');
  test.setTimeout(240_000);
  await openKeel(page, {path: '/companies'});
  await page.getByTestId('add-ticker').fill('zts');
  await page.getByTestId('add-submit').click();
  const card = page.getByTestId('job-card');
  await expect(card).toBeVisible();
  // The plan is there from the start, every step pending or running.
  const steps = card.getByTestId('job-step');
  await expect(steps).toHaveCount(ADD_STEPS.length);
  await expect(steps.first()).toContainText('Prepare the corpus');
  expect(
    await steps.evaluateAll(rows => rows.map(r => r.getAttribute('data-key'))),
  ).toEqual(ADD_STEPS);
  // Sample the marks while the job runs: the steps that ended always come
  // first, in plan order, and at most 1 step runs at a time.
  const seen = new Set<string>();
  for (let i = 0; i < 1200; i++) {
    const marks = await steps.evaluateAll(rows =>
      rows.map(row => row.getAttribute('data-status') ?? ''),
    );
    seen.add(marks.join(','));
    const firstOpen = marks.findIndex(m => m === 'pending' || m === 'running');
    if (firstOpen >= 0) {
      expect(
        marks.slice(firstOpen + 1).every(m => m === 'pending'),
        marks.join(','),
      ).toBe(true);
    }
    expect(marks.filter(m => m === 'running').length).toBeLessThanOrEqual(1);
    if ((await card.getAttribute('data-status')) === 'succeeded') {
      break;
    }
    await page.waitForTimeout(100);
  }
  await expect(card).toHaveAttribute('data-status', 'succeeded', {
    timeout: 180_000,
  });
  // More than 1 state was seen on the way: the marks moved step by step.
  expect(seen.size).toBeGreaterThan(1);
  await expect(steps.locator('[data-testid="job-step-icon"]')).toHaveText(
    ADD_STEPS.map(() => 'succeeded'),
  );
  await expect(card.getByTestId('job-progress')).toContainText(
    `${ADD_STEPS.length} of ${ADD_STEPS.length} steps`,
  );
  // A finished step opens its log on a click.
  const embed = card.locator('[data-testid="job-step"][data-key="embed"]');
  await embed.getByTestId('job-step-toggle').click();
  await expect(embed.getByRole('log')).toContainText('chunks embedded');
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
