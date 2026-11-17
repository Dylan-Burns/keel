import {fireEvent, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {ACCESS_KEY, getAccessMode, setAccessMode} from '../api/access';
import {TOKEN_KEY} from '../api/client';
import {AccessGate} from './AccessGate';

/**
 * Stubs fetch: `/api/ready` reports the access mode, the admin probe
 * answers with the given status.
 */
function serve(
  access: 'public' | 'token' | null,
  probeStatus = 200,
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.startsWith('/api/ready')
      ? {
          ready: true,
          index_version: 'v1',
          checks: {index_loaded: true, provider_key: true},
          ...(access === null ? {} : {access}),
        }
      : {};
    const status = url.startsWith('/api/ready') ? 200 : probeStatus;
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: {'Content-Type': 'application/json'},
      }),
    );
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function calledPaths(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map(call => String(call[0]));
}

describe('AccessGate', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setAccessMode(null);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('lets a visitor of a public service straight in', async () => {
    const fetchMock = serve('public');
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    expect(await screen.findByText('the page')).toBeInTheDocument();
    expect(screen.queryByTestId('no-access')).toBeNull();
    expect(getAccessMode()).toBe('public');
    expect(window.sessionStorage.getItem(ACCESS_KEY)).toBe('public');
    // No role probe for a visitor.
    expect(calledPaths(fetchMock)).toEqual(['/api/ready']);
  });

  it('keeps the token gate in token mode', async () => {
    serve('token');
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    expect(await screen.findByTestId('no-access')).toBeInTheDocument();
    expect(screen.queryByText('the page')).toBeNull();
    expect(screen.queryByTestId('no-access-skip')).toBeNull();
  });

  it('treats a server without the access field as token mode', async () => {
    serve(null);
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    expect(await screen.findByTestId('no-access')).toBeInTheDocument();
    expect(getAccessMode()).toBe('token');
  });

  it('shows no gate before the mode is known', () => {
    serve('public');
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    expect(screen.getByTestId('access-checking')).toBeInTheDocument();
    expect(screen.queryByTestId('no-access')).toBeNull();
  });

  it('renders at once on a later load of a public service', () => {
    window.sessionStorage.setItem(ACCESS_KEY, 'public');
    serve('public');
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    expect(screen.getByText('the page')).toBeInTheDocument();
  });

  it('refuses a wrong admin token on a public service, then lets the visitor on', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'wrong');
    serve('public', 401);
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    expect(
      await screen.findByRole('heading', {name: 'Access token rejected'}),
    ).toBeInTheDocument();
    expect(screen.queryByText('the page')).toBeNull();
    fireEvent.click(screen.getByTestId('no-access-skip'));
    expect(await screen.findByText('the page')).toBeInTheDocument();
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it('lets an admin token through on a public service', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'admin-token');
    serve('public', 200);
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    expect(await screen.findByText('the page')).toBeInTheDocument();
  });
});
