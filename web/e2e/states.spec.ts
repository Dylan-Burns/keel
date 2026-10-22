import {expect, test} from '@playwright/test';

import {openKeel, stateRoot, statesSeen} from './support/api';

// The 11 states of table 14.6, driven by the mock provider fault header
// X-Keel-Mock (live) or the same faults in the route mocks (mocked).

test('empty: the question area, the examples, and the coverage summary', async ({
  page,
}) => {
  await openKeel(page);
  await expect(stateRoot(page)).toHaveAttribute('data-state', 'empty');
  await expect(page.getByTestId('example-chip')).toHaveCount(3);
  await expect(page.getByTestId('coverage-summary')).toContainText('companies');
  await expect(page.getByTestId('index-version')).toBeVisible();
});

test('loading, streaming, complete: example question 2', async ({page}) => {
  await openKeel(page);
  await page.getByTestId('example-chip').nth(1).click();
  await expect(stateRoot(page)).toHaveAttribute('data-state', 'complete');
  const seen = await statesSeen(page);
  expect(seen).toEqual(['empty', 'loading', 'streaming', 'complete']);
  await expect(page.getByTestId('citation-chip').first()).toBeEnabled();
  await expect(page.getByTestId('cost-badge')).toBeVisible();
});

test('partial_coverage: the yellow banner names the absent company', async ({
  page,
}) => {
  await openKeel(page, {fault: 'partial_coverage'});
  await page.getByTestId('example-chip').first().click();
  await expect(stateRoot(page)).toHaveAttribute(
    'data-state',
    'partial_coverage',
  );
  await expect(page.getByTestId('banner-partial-coverage')).toContainText(
    'TSLA',
  );
});

test('out_of_scope: the gray card with the reason and the examples', async ({
  page,
}) => {
  await openKeel(page, {fault: 'out_of_scope'});
  await page
    .getByRole('textbox')
    .fill('What will the NVIDIA share price be next year?');
  await page.getByRole('button', {name: 'Ask'}).click();
  await expect(stateRoot(page)).toHaveAttribute('data-state', 'out_of_scope');
  const card = page.getByTestId('card-out-of-scope');
  await expect(card).toBeVisible();
  await expect(card.getByTestId('example-chip')).toHaveCount(3);
});

test('rate_limited: a countdown, and Ask stays off until it ends', async ({
  page,
}) => {
  await openKeel(page, {fault: 'rate_limited'});
  await page.getByTestId('example-chip').first().click();
  await expect(stateRoot(page)).toHaveAttribute('data-state', 'rate_limited');
  await expect(page.getByTestId('card-rate-limited')).toBeVisible();
  await expect(page.getByRole('button', {name: 'Ask'})).toBeDisabled();
  await expect(page.getByTestId('card-rate-limited')).toBeHidden({
    timeout: 10_000,
  });
  await expect(page.getByRole('button', {name: 'Ask'})).toBeEnabled();
});

test('provider_down: the red banner, the retrieved chunks, and Retry', async ({
  page,
}) => {
  await openKeel(page, {fault: 'provider_unavailable'});
  await page.getByTestId('example-chip').first().click();
  await expect(stateRoot(page)).toHaveAttribute('data-state', 'provider_down');
  const banner = page.getByTestId('banner-provider-down');
  await expect(banner).toContainText('Model unavailable');
  await expect(banner.getByRole('button', {name: 'Retry'})).toBeEnabled();
  await expect(page.getByTestId('chunk-row').first()).toBeAttached();
});

test('index_not_built: the full-page card with the build command', async ({
  page,
}) => {
  await openKeel(page, {fault: 'index_not_built'});
  await expect(stateRoot(page)).toHaveAttribute(
    'data-state',
    'index_not_built',
  );
  await expect(page.getByTestId('card-index-not-built')).toContainText(
    'keel index',
  );
  await expect(page.getByTestId('health-dot')).toHaveAttribute(
    'data-health',
    'red',
  );
});

test('stale_index: the amber banner, and the index still serves', async ({
  page,
}) => {
  await openKeel(page, {fault: 'stale_index'});
  await expect(page.getByTestId('banner-stale-index')).toContainText(
    'keel index',
  );
  await expect(page.getByTestId('health-dot')).toHaveAttribute(
    'data-health',
    'amber',
  );
  await page.getByTestId('example-chip').nth(1).click();
  await expect(page.getByTestId('answer-markdown')).toBeVisible();
  await expect(page.getByTestId('banner-stale-index')).toBeVisible();
});

test('network_offline: the red banner, and the last answer stays', async ({
  page,
  context,
}) => {
  await openKeel(page);
  await page.getByTestId('example-chip').nth(1).click();
  await expect(stateRoot(page)).toHaveAttribute('data-state', 'complete');
  const answer = await page.getByTestId('answer-markdown').innerText();
  await context.setOffline(true);
  await expect(page.getByTestId('banner-offline')).toBeVisible();
  await expect(page.getByTestId('answer-markdown')).toHaveText(answer);
  await expect(page.getByRole('button', {name: 'Ask'})).toBeDisabled();
  await context.setOffline(false);
  await expect(page.getByTestId('banner-offline')).toBeHidden();
  await expect(stateRoot(page)).toHaveAttribute('data-state', 'complete');
});
