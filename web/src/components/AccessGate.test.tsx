import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../api/client';
import {ACCEPTED_KEY, AccessGate, fingerprint} from './AccessGate';

/** Stubs fetch: the admin probe answers with the given status. */
function probe(status: number): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(() =>
    Promise.resolve(
      new Response(JSON.stringify({}), {
        status,
        headers: {'Content-Type': 'application/json'},
      }),
    ),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('AccessGate', () => {
  beforeEach(() => window.sessionStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it('shows only the gate without a token, then the page once accepted', async () => {
    const fetchMock = probe(200);
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    expect(screen.getByTestId('no-access')).toBeInTheDocument();
    expect(screen.queryByText('the page')).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Access token'), {
      target: {value: 'good-token'},
    });
    fireEvent.click(screen.getByRole('button', {name: 'Continue'}));
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBe('good-token');
    expect(await screen.findByText('the page')).toBeInTheDocument();
    expect(screen.queryByTestId('no-access')).toBeNull();
  });

  it('keeps a rejected token at the gate', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'bad-token');
    probe(401);
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    await waitFor(() =>
      expect(
        screen.getByRole('heading', {name: 'Access token rejected'}),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText('the page')).toBeNull();
  });

  it('lets an analyst token through', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'analyst-token');
    probe(403);
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    expect(await screen.findByText('the page')).toBeInTheDocument();
  });

  it('renders the page at once on a later load of an accepted token', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'good-token');
    window.sessionStorage.setItem(ACCEPTED_KEY, fingerprint('good-token'));
    probe(200);
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    // No gate while the check runs again.
    expect(screen.getByText('the page')).toBeInTheDocument();
    expect(screen.queryByTestId('no-access')).toBeNull();
    expect(await screen.findByText('the page')).toBeInTheDocument();
  });

  it('returns to the gate when a remembered token is refused', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'old-token');
    window.sessionStorage.setItem(ACCEPTED_KEY, fingerprint('old-token'));
    probe(401);
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    expect(screen.getByText('the page')).toBeInTheDocument();
    expect(
      await screen.findByRole('heading', {name: 'Access token rejected'}),
    ).toBeInTheDocument();
    expect(window.sessionStorage.getItem(ACCEPTED_KEY)).toBeNull();
  });

  it('checks a token the tab has not seen accepted before', () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'new-token');
    window.sessionStorage.setItem(ACCEPTED_KEY, fingerprint('old-token'));
    probe(200);
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    expect(screen.getByTestId('no-access')).toBeInTheDocument();
    expect(screen.queryByText('the page')).toBeNull();
  });

  it('remembers a token the server accepted', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'good-token');
    probe(200);
    render(
      <AccessGate>
        <p>the page</p>
      </AccessGate>,
    );
    await screen.findByText('the page');
    expect(window.sessionStorage.getItem(ACCEPTED_KEY)).toBe(
      fingerprint('good-token'),
    );
  });
});
