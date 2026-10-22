import {expect, test} from '@playwright/test';

import {openKeel, stateRoot} from './support/api';

// Chapter 27.2: the history page per user, the shareable link of a stored
// answer, and the re-run button. Live mode asks as the legacy token user.
test('an answer appears in the history and opens read-only at its link', async ({
  page,
}) => {
  await openKeel(page);
  await page.getByTestId('example-chip').nth(1).click();
  await expect(stateRoot(page)).toHaveAttribute(
    'data-state',
    /^(complete|partial_coverage)$/,
  );
  await expect(page.getByTestId('share-link')).toBeEnabled();
  const footer = await page.getByTestId('request-id').textContent();
  const requestId = (footer ?? '').replace('request ', '').trim();
  expect(requestId).not.toBe('');

  // The history lists the question, newest first, with its stored answer.
  await page.getByTestId('history-link').click();
  await expect(page).toHaveURL(/\/history$/);
  const item = page.locator(
    `[data-testid="history-item"][data-request-id="${requestId}"]`,
  );
  await expect(item).toBeVisible();
  await expect(item).toContainText('NVIDIA');
  await expect(page.getByTestId('history-item').first()).toHaveAttribute(
    'data-request-id',
    requestId,
  );

  // The link opens the stored answer, read-only.
  await item.getByTestId('history-open').click();
  await expect(page).toHaveURL(new RegExp(`/a/${requestId}$`));
  await expect(page.getByTestId('shared-notice')).toHaveAttribute(
    'data-load',
    'loaded',
  );
  await expect(page.getByTestId('answer-markdown')).not.toBeEmpty();
  await expect(page.getByTestId('request-id')).toContainText(requestId);
});

test('re-run puts a question of the history back in the question box', async ({
  page,
}) => {
  await openKeel(page, {path: '/history'});
  const first = page.getByTestId('history-item').first();
  await expect(first).toBeVisible();
  const question = await first.locator('p').first().textContent();
  await first.getByTestId('history-rerun').click();
  await expect(page).toHaveURL(/\/$/);
  // Re-run fills the question box; nothing is sent until the user asks.
  const box = page.getByRole('textbox', {name: 'Question'});
  await expect(box).toHaveValue(question ?? '');
  await expect(stateRoot(page)).toHaveAttribute('data-state', 'empty');
  await page.getByRole('button', {name: 'Ask', exact: true}).click();
  await expect(stateRoot(page)).toHaveAttribute(
    'data-state',
    /^(complete|partial_coverage)$/,
  );
});

test('a link to an answer that no store holds says so', async ({page}) => {
  await openKeel(page, {path: '/a/no-such-answer'});
  await expect(page.getByTestId('shared-notice')).toHaveAttribute(
    'data-load',
    'missing',
  );
});
