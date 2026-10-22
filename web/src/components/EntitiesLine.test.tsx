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

  it('names each comp set and its tickers outside the index', () => {
    render(
      <EntitiesLine
        analysis={{
          tickers: ['MSFT', 'ORCL'],
          primary_type: 'comparison',
          time_scope: {kind: 'none'},
          comp_sets: [
            {
              name: 'software',
              text: 'my software comps',
              tickers: ['MSFT', 'ORCL', 'WDAY'],
              missing: ['WDAY'],
            },
          ],
        }}
      />,
    );
    expect(screen.getByTestId('comp-set-note')).toHaveTextContent(
      '"my software comps" is the comp set software; not in the index: WDAY',
    );
  });
});
