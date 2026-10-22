import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {EntitiesLine} from './EntitiesLine';

describe('EntitiesLine', () => {
  it('shows nothing before the analysis', () => {
    const {container} = render(<EntitiesLine analysis={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the tickers and a did-you-mean note after a fuzzy match', () => {
    render(
      <EntitiesLine
        analysis={{
          tickers: ['JPM', 'AAPL'],
          primary_type: 'comparison',
          time_scope: {kind: 'none'},
          entities: [
            {
              ticker: 'JPM',
              company: 'JPMorgan Chase & Co.',
              text: 'JP Morgen',
              rule: 'fuzzy',
              fuzzy: true,
            },
          ],
        }}
      />,
    );
    expect(
      screen.getAllByTestId('entity-chip').map(c => c.textContent),
    ).toEqual(['JPM', 'AAPL']);
    expect(screen.getByText(/Did you mean JPMorgan Chase/)).toBeInTheDocument();
  });
});
