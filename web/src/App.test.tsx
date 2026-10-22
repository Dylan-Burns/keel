import {render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {App} from './App';
import {READY} from './testing/fixtures';

afterEach(() => vi.unstubAllGlobals());

describe('App', () => {
  it('renders the name Keel as the page heading and the example chips', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(READY))),
    );
    render(<App />);
    expect(
      screen.getByRole('heading', {level: 1, name: 'Keel'}),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId('example-chip')).toHaveLength(3);
    expect(await screen.findByText('index 1.0.0')).toBeInTheDocument();
  });
});
