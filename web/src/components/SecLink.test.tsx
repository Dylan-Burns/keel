import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {SecLink} from './SecLink';

describe('SecLink', () => {
  it('links to www.sec.gov in a new tab', () => {
    render(<SecLink url="https://www.sec.gov/a.htm" />);
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', 'https://www.sec.gov/a.htm');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('says that a deep link jumps to the excerpt', () => {
    render(<SecLink url="https://www.sec.gov/a.htm#:~:text=Risk%20factors" />);
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('data-deep', 'true');
    expect(link).toHaveAttribute('title');
    expect(screen.getByTestId('excerpt-hint')).toHaveTextContent(
      'jumps to the excerpt',
    );
  });

  it('shows no hint on a plain link', () => {
    render(<SecLink url="https://www.sec.gov/a.htm" />);
    expect(screen.queryByTestId('excerpt-hint')).toBeNull();
  });

  it('renders any other URL as text', () => {
    render(<SecLink url="https://evil.example/x" label="Filing" />);
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByTestId('untrusted-url')).toHaveTextContent(
      'https://evil.example/x',
    );
  });

  it('renders nothing without a URL', () => {
    const {container} = render(<SecLink url={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
