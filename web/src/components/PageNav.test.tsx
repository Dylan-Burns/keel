import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {PageNav} from './PageNav';

describe('PageNav', () => {
  it('links every page by its path', () => {
    render(<PageNav />);
    expect(screen.getByTestId('history-link')).toHaveAttribute(
      'href',
      '/history',
    );
    expect(screen.getByTestId('compsets-link')).toHaveAttribute(
      'href',
      '/compsets',
    );
    expect(screen.getByTestId('financials-link')).toHaveAttribute(
      'href',
      '/financials',
    );
    expect(screen.getByTestId('companies-link')).toHaveAttribute(
      'href',
      '/companies',
    );
    expect(screen.getByTestId('eval-link')).toHaveAttribute('href', '/eval');
    expect(screen.getByTestId('debug-link')).toHaveAttribute('href', '/debug');
    expect(screen.getByTestId('help-link')).toHaveAttribute('href', '/help');
  });

  it('shows the admin links only to an admin, in their own group', () => {
    const {rerender} = render(<PageNav />);
    expect(screen.queryByTestId('admin-links')).toBeNull();
    expect(screen.queryByTestId('jobs-link')).toBeNull();
    rerender(<PageNav isAdmin />);
    const admin = screen.getByTestId('admin-links');
    expect(admin).toContainElement(screen.getByTestId('jobs-link'));
    expect(admin).toContainElement(screen.getByTestId('users-link'));
    expect(admin).toContainElement(screen.getByTestId('system-link'));
    expect(screen.getByTestId('page-links')).not.toContainElement(
      screen.getByTestId('jobs-link'),
    );
  });
});
