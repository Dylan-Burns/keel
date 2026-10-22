import {expect, test} from '@playwright/test';

import {openKeel} from './support/api';

test('the eval page renders the report and the prompt log read-only (W-02)', async ({
  page,
}) => {
  await openKeel(page, {path: '/eval'});
  const root = page.getByTestId('eval-page');
  await expect(root).toHaveAttribute('data-load', 'ready');
  // Before stage 10 ships eval/report.md the report shows its empty state;
  // with the report, the gates show as bars with their numbers.
  const report = page.getByTestId('eval-report');
  await expect(report).toBeVisible();
  const gates = page.getByTestId('eval-gate');
  if ((await gates.count()) === 0) {
    await expect(page.getByTestId('eval-no-gates')).toBeVisible();
  } else {
    await expect(gates.first().getByTestId('eval-gate-value')).toBeVisible();
  }
  await expect(page.getByTestId('eval-prompt-log')).toBeVisible();
  await expect(page.locator('script:not([src])')).toHaveCount(0);
});
