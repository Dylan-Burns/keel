import {fireEvent, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {
  AUDIT_RETENTION_MONTHS,
  DATA_USE_SECTIONS,
  HelpPage,
  RESTORE_TESTED_ON,
} from './HelpPage';

const assign = vi.fn();

beforeEach(() => {
  assign.mockReset();
  vi.stubGlobal('location', {...window.location, assign});
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('HelpPage', () => {
  it('states what goes to the model provider and to SEC EDGAR', () => {
    render(<HelpPage />);
    expect(screen.getByTestId('help-model-provider')).toHaveTextContent(
      'exactly 1 request to the Anthropic API',
    );
    expect(screen.getByTestId('help-model-provider')).toHaveTextContent(
      'filing excerpts',
    );
    expect(screen.getByTestId('help-sec-edgar')).toHaveTextContent(
      'No question and no answer goes to the SEC',
    );
  });

  it('states the logs, the retention, the history, and the restore date', () => {
    render(<HelpPage />);
    expect(screen.getByTestId('help-logs')).toHaveTextContent(
      `${AUDIT_RETENTION_MONTHS} months`,
    );
    expect(screen.getByTestId('help-logs')).toHaveTextContent(
      'never holds the prompt text',
    );
    expect(screen.getByTestId('help-history')).toHaveTextContent('admin');
    expect(screen.getByTestId('help-backups')).toHaveTextContent(
      RESTORE_TESTED_ON,
    );
    expect(RESTORE_TESTED_ON).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('renders every section with a heading and no external link', () => {
    const {container} = render(<HelpPage />);
    expect(screen.getAllByRole('heading', {level: 2})).toHaveLength(
      DATA_USE_SECTIONS.length,
    );
    expect(container.querySelectorAll('a[href]')).toHaveLength(0);
  });

  it('goes back to the question page', () => {
    render(<HelpPage />);
    fireEvent.click(screen.getByRole('button', {name: 'Back to questions'}));
    expect(assign).toHaveBeenCalledWith('/');
  });
});
