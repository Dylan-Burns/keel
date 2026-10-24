import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {BrandLink} from './BrandLink';
import {PageBar} from './PageBar';

describe('BrandLink', () => {
  it('links the logo and name to the questions page', () => {
    render(<BrandLink />);
    const link = screen.getByRole('link', {name: 'Keel'});
    expect(link).toHaveAttribute('href', '/');
    expect(link).toHaveTextContent('Keel');
  });

  it('shows in the page bar of the inner pages', () => {
    render(<PageBar title="History" />);
    expect(screen.getByTestId('brand-link')).toHaveAttribute('href', '/');
  });
});
