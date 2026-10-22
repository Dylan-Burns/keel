import {render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../../api/client';
import {FORBIDDEN, SYSTEM, routeFetch} from '../../testing/admin';
import {SystemPage} from './SystemPage';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('SystemPage', () => {
  it('shows the doctor, the inventory, the index, the backups, and the audit', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    routeFetch({
      'GET /api/admin/jobs': {body: {items: [], active: null}},
      'GET /api/admin/system': {body: SYSTEM},
      'GET /api/admin/audit': {
        body: {
          items: [
            {
              at: '2026-10-22T18:00:00+00:00',
              user: 'carol',
              action: 'job.restore',
              target: null,
              params: {archive: 'keel-x.tar.gz'},
              outcome: 'confirm_mismatch',
            },
          ],
        },
      },
    });
    render(<SystemPage />);
    expect(await screen.findAllByTestId('doctor-row')).toHaveLength(2);
    expect(screen.getByTestId('sys-index')).toHaveTextContent('1.0.0');
    expect(screen.getByTestId('sys-inventory')).toHaveTextContent('10-K 2');
    expect(screen.getByTestId('sys-service')).toHaveTextContent(
      '$0.00 of $20.00',
    );
    expect(screen.getByTestId('backup-row')).toHaveTextContent('120.6 KB');
    expect(await screen.findByTestId('audit-row')).toHaveTextContent(
      'confirm_mismatch',
    );
  });

  it('never loads the system data for an analyst', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'token');
    const calls = routeFetch({'GET /api/admin/jobs': FORBIDDEN});
    render(<SystemPage />);
    expect(await screen.findByTestId('admin-only')).toBeInTheDocument();
    expect(calls.map(c => c.path)).toEqual(['/api/admin/jobs?limit=1']);
  });
});
