import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {MarkdownDocument, splitSections} from './MarkdownDocument';

describe('MarkdownDocument', () => {
  it('splits at headings but not inside a code fence', () => {
    expect(
      splitSections(
        'intro\n# Title #\nbody\n```\n# not a heading\n```\n### Sub',
      ),
    ).toEqual([
      {heading: null, level: 0, body: 'intro'},
      {heading: 'Title', level: 1, body: 'body\n```\n# not a heading\n```'},
      {heading: 'Sub', level: 3, body: ''},
    ]);
  });

  it('renders headings as text and notes a truncated file', () => {
    render(
      <MarkdownDocument
        title="Eval report"
        document={{
          source: 'eval/report.md',
          markdown: '## <b>Gates</b>\n\nText\n\n### Deep',
          truncated: true,
        }}
        empty="none"
        testId="doc"
      />,
    );
    expect(
      screen.getByRole('heading', {name: '<b>Gates</b>'}),
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', {name: 'Deep'})).toBeInTheDocument();
    expect(screen.getByTestId('doc')).toHaveTextContent('longer than the page');
  });
});
