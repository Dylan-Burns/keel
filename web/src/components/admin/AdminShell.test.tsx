import {render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../../api/client';
import {FORBIDDEN, routeFetch} from '../../testing/admin';
import {AdminShell} from './AdminShell';

afterEach(() => {
  vi.unstubAllGlobals();
});

function shell(adminOnly: boolean): void {
  render(
    <AdminShell title="Jobs" current="jobs" adminOnly={adminOnly} testId="page">
      {isAdmin => <p data-testid="body">{isAdmin ? 'admin' : 'member'}</p>}
    </AdminShell>,
  );
}

describe('AdminShell', () => {
  it('shows every operations page and the body to an admin', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'admin-token');
    const calls = routeFetch({
      'GET /api/admin/jobs': {body: {items: [], active: null}},
    });
    shell(true);
    expect(await screen.findByTestId('body')).toHaveTextContent('admin');
    expect(screen.getByTestId('page')).toHaveAttribute('data-role', 'admin');
    for (const page of ['companies', 'jobs', 'users', 'system', 'debug']) {
      expect(screen.getByTestId(`ops-link-${page}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId('ops-link-jobs')).toHaveAttribute(
      'aria-current',
      'page',
    );
    // The role comes from a probe of an admin route, with the token.
    expect(calls[0]?.path).toBe('/api/admin/jobs?limit=1');
  });

  it('keeps an admin page from an analyst and hides the admin links', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'analyst-token');
    routeFetch({'GET /api/admin/jobs': FORBIDDEN});
    shell(true);
    expect(await screen.findByTestId('admin-only')).toHaveTextContent(
      'This page is for admins.',
    );
    expect(screen.queryByTestId('body')).toBeNull();
    expect(screen.getByTestId('ops-link-companies')).toBeInTheDocument();
    expect(screen.getByTestId('ops-link-debug')).toBeInTheDocument();
    expect(screen.queryByTestId('ops-link-jobs')).toBeNull();
    expect(screen.queryByTestId('ops-link-users')).toBeNull();
    expect(screen.queryByTestId('ops-link-system')).toBeNull();
  });

  it('shows a page open to every role to an analyst', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'analyst-token');
    routeFetch({'GET /api/admin/jobs': FORBIDDEN});
    shell(false);
    expect(await screen.findByTestId('body')).toHaveTextContent('member');
    expect(screen.queryByTestId('admin-only')).toBeNull();
  });

  it('asks for a token, and says so when the token is rejected', async () => {
    routeFetch({});
    shell(true);
    expect(screen.getByText('Enter your access token to open this page.'));
    expect(screen.queryByTestId('ops-nav')).toBeNull();
  });

  it('reports a rejected token', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'wrong');
    routeFetch({
      'GET /api/admin/jobs': {
        status: 401,
        body: {detail: {code: 'unauthorized', message: 'no'}},
      },
    });
    shell(true);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The token was rejected.',
    );
    expect(screen.queryByTestId('body')).toBeNull();
  });
});
