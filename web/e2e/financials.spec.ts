import type {Page} from '@playwright/test';
import {expect, test} from '@playwright/test';

import {openKeel, stateRoot} from './support/api';

// The financials page: a checked row adds a bar series, the period
// switches to quarterly, and an answer's company tag opens the page. Live,
// the page reads the recorded NVIDIA company facts of tests/fixtures/edgar.

async function ready(page: Page): Promise<void> {
  await expect(page.getByTestId('financials-page')).toHaveAttribute(
    'data-load',
    'ready',
  );
}

test('checking a row adds a bar series', async ({page}) => {
  await openKeel(page, {path: '/financials?ticker=NVDA'});
  await ready(page);
  const charts = page.getByTestId('fin-charts');
  await expect(charts).toHaveAttribute('data-series', '2');
  await expect(page.getByTestId('fin-chart')).toHaveCount(1);
  await page.locator('[data-row="eps_diluted"]').getByRole('checkbox').click();
  await expect(charts).toHaveAttribute('data-series', '3');
  // Per-share values get their own chart under the dollar chart.
  await expect(page.getByTestId('fin-chart')).toHaveCount(2);
  await expect(page.getByTestId('fin-legend')).toContainText('Diluted EPS');
  // A period's tooltip names the filing behind each value.
  await page.getByTestId('fin-band').last().click();
  const tip = page.getByTestId('fin-tooltip');
  await expect(tip).toHaveAttribute('data-pinned', 'true');
  await expect(tip.getByRole('link', {name: 'filing'}).first()).toHaveAttribute(
    'href',
    /^https:\/\/www\.sec\.gov\/Archives\/edgar\/data\/1045810\//,
  );
  await page.keyboard.press('Escape');
  await expect(tip).toHaveCount(0);
});

test('switching to quarterly shows the fiscal quarters', async ({page}) => {
  await openKeel(page, {path: '/financials?ticker=NVDA'});
  await ready(page);
  await expect(page.getByTestId('fin-table')).not.toContainText(/Q\d FY/);
  await page.getByTestId('fin-period-quarterly').click();
  await expect(page.getByTestId('financials-page')).toHaveAttribute(
    'data-period',
    'quarterly',
  );
  await ready(page);
  await expect(page.getByTestId('fin-table')).toContainText(/Q\d FY\d{4}/);
  await expect(page.getByTestId('fin-bar').first()).toBeVisible();
});

test("an answer's company tag opens the financials page", async ({page}) => {
  await openKeel(page);
  await page.getByTestId('example-chip').nth(1).click();
  await expect(stateRoot(page)).toHaveAttribute(
    'data-state',
    /^(complete|partial_coverage)$/,
  );
  await page.getByTestId('entity-chip').filter({hasText: 'NVDA'}).click();
  await expect(page).toHaveURL(/\/financials\?ticker=NVDA$/);
  await ready(page);
  await expect(page.getByTestId('financials-page')).toHaveAttribute(
    'data-ticker',
    'NVDA',
  );
});
