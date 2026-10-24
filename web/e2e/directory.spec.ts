import {expect, test} from '@playwright/test';

import type {IndustryCompanies} from '../src/api/types';
import {isLive, openKeel} from './support/api';

// The company browser of the companies page (docs/API_ADMIN.md) against
// `keel serve` with the mock provider. The EDGAR cache of the server holds
// the recorded responses of tests/fixtures/edgar: the ticker map and the
// company list of SIC 3674, so no request reaches the SEC. The spec never
// presses Add: the add job changes the index, and ops-jobs.spec.ts runs
// it last.

test('an admin browses a sector, an industry, and its companies', async ({
  page,
}) => {
  test.skip(!isLive, 'the company browser needs keel serve');
  await openKeel(page, {path: '/companies'});
  const browser = page.getByTestId('browse');
  await expect(browser).toBeVisible();
  const sector = browser.locator(
    '[data-testid="sector-row"][data-sector="Manufacturing"]',
  );
  const sectorToggle = sector.getByTestId('sector-toggle');
  await expect(sectorToggle).toHaveAttribute('aria-expanded', 'false');
  // The keyboard opens a row: the toggle is a button.
  await sectorToggle.focus();
  await page.keyboard.press('Enter');
  await expect(sectorToggle).toHaveAttribute('aria-expanded', 'true');
  const industry = browser.locator(
    '[data-testid="industry-row"][data-code="3674"]',
  );
  await expect(industry).toContainText('SEMICONDUCTORS');
  const loaded = page.waitForResponse(r =>
    r.url().endsWith('/api/admin/directory/sic/3674'),
  );
  await industry.getByTestId('industry-toggle').focus();
  await page.keyboard.press('Space');
  const body = (await (await loaded).json()) as IndustryCompanies;
  expect(body.sec_requests).toBe(0);
  const rows = browser.getByTestId('company-row');
  await expect(rows).toHaveCount(3);
  expect(
    await rows.evaluateAll(all => all.map(r => r.getAttribute('data-ticker'))),
  ).toEqual(['AMD', 'INTC', 'NVDA']);
  const nvda = browser.locator(
    '[data-testid="company-row"][data-ticker="NVDA"]',
  );
  await expect(nvda.getByTestId('badge-indexed')).toBeVisible();
  await expect(nvda.getByTestId('company-add')).toHaveText('Update');
  const amd = browser.locator('[data-testid="company-row"][data-ticker="AMD"]');
  await expect(amd.getByTestId('badge-indexed')).toHaveCount(0);
  await expect(amd.getByTestId('company-add')).toBeEnabled();

  // The search finds a company outside the open industry.
  await browser.getByTestId('browse-search').fill('zoetis');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toHaveAttribute('data-ticker', 'ZTS');
  await expect(browser.getByTestId('sector-row')).toHaveCount(0);
  await browser.getByTestId('browse-search').fill('');
  await expect(sector).toBeVisible();
});
