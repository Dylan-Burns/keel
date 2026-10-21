import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {App} from './App';
import {pageLoad, pick} from './motion/presets';

describe('App', () => {
  it('renders the name Keel as the page heading', () => {
    render(<App />);
    expect(
      screen.getByRole('heading', {level: 1, name: 'Keel'}),
    ).toBeInTheDocument();
  });
});

describe('pick', () => {
  it('uses the reduced twin only when reduced motion is true', () => {
    expect(pick(pageLoad, true)).toBe(pageLoad.reduced);
    expect(pick(pageLoad, false)).toBe(pageLoad.full);
    expect(pick(pageLoad, null)).toBe(pageLoad.full);
  });
});
