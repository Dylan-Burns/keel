import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {routeFetch} from '../../testing/admin';
import {UsersPanel} from './UsersPanel';

const TOKEN = 'shown-once-token';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('UsersPanel', () => {
  it('shows a new token once, copies it, and forgets it', async () => {
    let users = [{name: 'alice', role: 'analyst'}];
    const calls = routeFetch({
      ['GET /api/admin/users']: () => ({
        body: {items: users, legacy_enabled: true},
      }),
      ['POST /api/admin/users']: call => {
        users = [...users, {name: 'dave', role: 'partner'}];
        return {
          status: 201,
          body: {...(call.body as object), token: TOKEN},
        };
      },
    });
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal('navigator', {...navigator, clipboard: {writeText}});
    render(<UsersPanel />);
    expect(await screen.findByTestId('users-legacy')).toBeInTheDocument();
    fireEvent.change(screen.getByTestId('user-name'), {
      target: {value: 'Dave'},
    });
    fireEvent.change(screen.getByTestId('user-role'), {
      target: {value: 'partner'},
    });
    fireEvent.click(screen.getByTestId('user-add'));
    expect(await screen.findByTestId('new-token-value')).toHaveTextContent(
      TOKEN,
    );
    expect(screen.getByTestId('new-token')).toHaveTextContent(
      "It won't be shown again.",
    );
    expect(calls.find(c => c.method === 'POST')?.body).toEqual({
      name: 'dave',
      role: 'partner',
    });
    fireEvent.click(screen.getByTestId('new-token-copy'));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(TOKEN));
    // The token lives only in the page state: no storage holds it.
    expect(JSON.stringify({...window.sessionStorage})).not.toContain(TOKEN);
    expect(JSON.stringify({...window.localStorage})).not.toContain(TOKEN);
    await screen.findAllByTestId('users-row');
    expect(screen.getAllByTestId('users-row')).toHaveLength(2);
    fireEvent.click(screen.getByTestId('new-token-dismiss'));
    expect(screen.queryByTestId('new-token')).toBeNull();
    expect(document.body.textContent).not.toContain(TOKEN);
  });

  it('removes a user after an inline confirmation', async () => {
    const calls = routeFetch({
      ['GET /api/admin/users']: {
        body: {
          items: [{name: 'alice', role: 'analyst'}],
          legacy_enabled: false,
        },
      },
      'DELETE /api/admin/users/alice': {status: 204},
    });
    render(<UsersPanel />);
    fireEvent.click(await screen.findByTestId('user-remove'));
    expect(screen.getByText('Remove alice? The token stops at once.'));
    expect(calls.some(c => c.method === 'DELETE')).toBe(false);
    fireEvent.click(screen.getByTestId('user-remove-confirm'));
    expect(await screen.findByTestId('user-notice')).toHaveTextContent(
      'Removed alice.',
    );
    expect(calls.filter(c => c.method === 'DELETE')).toHaveLength(1);
  });

  it('says why an add failed', async () => {
    routeFetch({
      ['GET /api/admin/users']: {body: {items: [], legacy_enabled: true}},
      ['POST /api/admin/users']: {
        status: 409,
        body: {detail: {code: 'user_exists', message: 'exists'}},
      },
    });
    render(<UsersPanel />);
    fireEvent.change(await screen.findByTestId('user-name'), {
      target: {value: 'alice'},
    });
    fireEvent.click(screen.getByTestId('user-add'));
    expect(await screen.findByTestId('user-notice')).toHaveTextContent(
      'A user with this name exists.',
    );
    expect(screen.queryByTestId('new-token')).toBeNull();
  });
});
