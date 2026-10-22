import {readFile} from 'node:fs/promises';

import type {APIRequestContext} from '@playwright/test';
import {expect, test} from '@playwright/test';

import {TOKEN, isLive, openKeel, stateRoot} from './support/api';

// The operations pages (docs/API_ADMIN.md): the role gate and the memo
// download. The role spec needs `keel serve` with the mock provider. The
// jobs that change the index run last, in ops-jobs.spec.ts.

/**
 * Adds a user through the admin API and returns its token.
 *
 * @param request The API context.
 * @param name The user name.
 * @param role The role.
 * @return The token, shown once by the API.
 */
async function addUser(
  request: APIRequestContext,
  name: string,
  role: string,
): Promise<string> {
  const headers = {Authorization: `Bearer ${TOKEN}`};
  // A user left by an earlier run would answer 409: remove it first.
  await request.delete(`/api/admin/users/${name}`, {headers});
  const response = await request.post('/api/admin/users', {
    headers,
    data: {name, role},
  });
  expect(response.status()).toBe(201);
  const body = (await response.json()) as {token: string};
  return body.token;
}

test('an admin sees the operations pages and an analyst does not', async ({
  page,
  request,
}, testInfo) => {
  test.skip(!isLive, 'the role check needs keel serve');
  await openKeel(page, {path: '/system'});
  await expect(page.getByTestId('system-page')).toHaveAttribute(
    'data-role',
    'admin',
  );
  await expect(page.getByTestId('sys-doctor')).toBeVisible();
  for (const name of ['companies', 'jobs', 'users', 'system', 'debug']) {
    await expect(page.getByTestId(`ops-link-${name}`)).toBeVisible();
  }

  const name = `e2e-analyst-${testInfo.project.name}`;
  const token = await addUser(request, name, 'analyst');
  const analyst = await page.context().newPage();
  await openKeel(analyst, {path: '/system', token});
  await expect(analyst.getByTestId('system-page')).toHaveAttribute(
    'data-role',
    'member',
  );
  await expect(analyst.getByTestId('admin-only')).toBeVisible();
  await expect(analyst.getByTestId('sys-doctor')).toHaveCount(0);
  await expect(analyst.getByTestId('ops-link-companies')).toBeVisible();
  await expect(analyst.getByTestId('ops-link-system')).toHaveCount(0);
  await expect(analyst.getByTestId('ops-link-jobs')).toHaveCount(0);
  // The watch list stays readable; the admin controls do not show.
  await analyst.getByTestId('ops-link-companies').click();
  await expect(analyst.getByTestId('watch')).toBeVisible();
  await expect(analyst.getByTestId('add-form')).toHaveCount(0);
  // The API refuses the route itself, whatever the page shows.
  const refused = await request.get('/api/admin/system', {
    headers: {Authorization: `Bearer ${token}`},
  });
  expect(refused.status()).toBe(403);
  await request.delete(`/api/admin/users/${name}`, {
    headers: {Authorization: `Bearer ${TOKEN}`},
  });
});

test('the memo of an answer downloads as markdown', async ({page}) => {
  await openKeel(page);
  await page.getByTestId('example-chip').nth(1).click();
  await expect(stateRoot(page)).toHaveAttribute(
    'data-state',
    /^(complete|partial_coverage)$/,
  );
  const footer = await page.getByTestId('request-id').textContent();
  const requestId = (footer ?? '').replace('request ', '').trim();
  const memo = page.getByTestId('memo-markdown');
  await expect(memo).toBeEnabled();
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    memo.click(),
  ]);
  expect(download.suggestedFilename()).toContain(requestId);
  expect(download.suggestedFilename()).toMatch(/\.md$/);
  const path = await download.path();
  const text = await readFile(path, 'utf8');
  expect(text).toMatch(/^# /);
  await expect(
    page.getByText(`Saved ${download.suggestedFilename()}`),
  ).toBeVisible();
});
