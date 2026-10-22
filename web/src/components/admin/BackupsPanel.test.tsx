import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../../api/client';
import {BACKUPS, routeFetch, submitted} from '../../testing/admin';
import {BackupsPanel} from './BackupsPanel';

const NAME = 'keel-2026-10-22T023000Z.tar.gz';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('BackupsPanel', () => {
  it('restores only after the exact archive name is typed', async () => {
    const calls = routeFetch({
      'POST /api/admin/jobs': {
        status: 202,
        body: submitted({kind: 'restore', params: {archive: NAME}}),
      },
      'GET /api/admin/jobs/3f2a9c0d1e4b5a67': {
        body: submitted({kind: 'restore'}),
      },
    });
    render(<BackupsPanel backups={BACKUPS} onDone={vi.fn()} />);
    fireEvent.click(screen.getByTestId('backup-restore'));
    const input = screen.getByTestId('restore-confirm-input');
    const submit = screen.getByTestId('restore-confirm-submit');
    expect(input).toHaveFocus();
    expect(submit).toBeDisabled();
    fireEvent.change(input, {target: {value: 'keel-2026-10-22'}});
    expect(submit).toBeDisabled();
    fireEvent.change(input, {target: {value: `${NAME} `}});
    expect(submit).toBeDisabled();
    fireEvent.change(input, {target: {value: NAME}});
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() =>
      expect(calls.find(c => c.method === 'POST')?.body).toEqual({
        kind: 'restore',
        params: {archive: NAME},
        confirm: NAME,
      }),
    );
    expect(await screen.findByTestId('job-card')).toBeInTheDocument();
  });

  it('cancels the restore with Escape and sends nothing', () => {
    const calls = routeFetch({});
    render(<BackupsPanel backups={BACKUPS} onDone={vi.fn()} />);
    fireEvent.click(screen.getByTestId('backup-restore'));
    fireEvent.keyDown(screen.getByTestId('restore-confirm-input'), {
      key: 'Escape',
    });
    expect(screen.queryByTestId('restore-confirm')).toBeNull();
    expect(calls).toHaveLength(0);
  });

  it('backs up now, index only when asked', async () => {
    const calls = routeFetch({
      'POST /api/admin/jobs': {status: 202, body: submitted({kind: 'backup'})},
    });
    render(<BackupsPanel backups={BACKUPS} onDone={vi.fn()} />);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('backup-now'));
    await waitFor(() =>
      expect(calls[0]?.body).toEqual({
        kind: 'backup',
        params: {index_only: true},
      }),
    );
  });

  it('downloads an archive with the token', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'admin-token');
    const fetchMock = vi.fn(() => Promise.resolve(new Response('gz')));
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: () => 'blob:a',
      revokeObjectURL: vi.fn(),
    });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});
    render(<BackupsPanel backups={BACKUPS} onDone={vi.fn()} />);
    fireEvent.click(screen.getByTestId('backup-download'));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/admin/backups/${encodeURIComponent(NAME)}`,
      {headers: {Authorization: 'Bearer admin-token'}},
    );
    expect(await screen.findByText(`Saved ${NAME}.`)).toBeInTheDocument();
  });
});
