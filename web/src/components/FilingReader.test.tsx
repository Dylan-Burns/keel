import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {CONTEXT_1} from '../testing/fixtures';
import {FilingReader} from './FilingReader';

const CITED = CONTEXT_1.chunk_id;
const OTHER = 'JPM_10K_2025-12-31__risk_factors__0003';
const QUOTE = 'The Company depends on component suppliers in Asia.';

afterEach(() => {
  vi.unstubAllGlobals();
});

function serve(body: unknown, status = 200): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(() =>
    Promise.resolve(new Response(JSON.stringify(body), {status})),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderReader(
  overrides: Partial<Parameters<typeof FilingReader>[0]> = {},
): {onNavigate: ReturnType<typeof vi.fn>; onClose: ReturnType<typeof vi.fn>} {
  const onNavigate = vi.fn();
  const onClose = vi.fn();
  render(
    <FilingReader
      chunkId={CITED}
      order={[CITED, OTHER]}
      quoteFor={() => QUOTE}
      onNavigate={onNavigate}
      onClose={onClose}
      {...overrides}
    />,
  );
  return {onNavigate, onClose};
}

describe('FilingReader', () => {
  it('shows the section with the quote marked and the filing header', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollTo =
      scroll as unknown as typeof Element.prototype.scrollTo;
    const fetchMock = serve(CONTEXT_1);
    renderReader();
    const mark = await screen.findByTestId('reader-mark');
    expect(mark.tagName).toBe('MARK');
    expect(mark).toHaveTextContent(QUOTE);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/chunks/${CITED}/context?before=4&after=4`,
    );
    const header = screen.getByTestId('reader-header');
    expect(header).toHaveTextContent('Apple Inc. (AAPL), 10-Q, Q1 FY2023');
    expect(header).toHaveTextContent('Part II, Item 1A. Risk Factors');
    expect(header).toHaveTextContent('Filed 2023-02-03');
    expect(screen.getByTestId('sec-link').getAttribute('href')).toContain(
      '#:~:text=The%20Company%20depends%20on%20component%20suppliers',
    );
    const passages = screen.getAllByTestId('reader-passage');
    expect(passages).toHaveLength(3);
    expect(passages[1]).toHaveAttribute('data-cited', 'true');
    // The table passage renders as a table.
    expect(screen.getByTestId('reader-table')).toHaveTextContent('96,388');
    await waitFor(() => expect(scroll).toHaveBeenCalled());
    expect(scroll.mock.contexts[0]).toBe(screen.getByTestId('reader-body'));
    expect(scroll.mock.calls[0]?.[0]).toMatchObject({top: 0});
  });

  it('navigates to the next citation and closes on Escape', async () => {
    serve(CONTEXT_1);
    const {onNavigate, onClose} = renderReader();
    await screen.findByTestId('reader-mark');
    expect(screen.getByTestId('reader-previous')).toBeDisabled();
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('reader-next'));
    expect(onNavigate).toHaveBeenCalledWith(OTHER);
    fireEvent.keyDown(window, {key: 'Escape'});
    expect(onClose).toHaveBeenCalled();
  });

  it('marks the whole cited passage when the quote is not in it', async () => {
    serve(CONTEXT_1);
    renderReader({quoteFor: () => 'not in the text'});
    const mark = await screen.findByTestId('reader-mark');
    expect(mark).toHaveTextContent('Supply is a risk.');
  });

  it('renders filing text as text, never as HTML', async () => {
    const passages = CONTEXT_1.passages.map(p =>
      p.cited ? {...p, text: '<img src=x onerror=alert(1)> risk'} : p,
    );
    serve({...CONTEXT_1, passages});
    renderReader({quoteFor: () => undefined});
    const mark = await screen.findByTestId('reader-mark');
    expect(mark).toHaveTextContent('<img src=x onerror=alert(1)> risk');
    expect(document.querySelector('img')).toBeNull();
  });

  it('says so when the text cannot be loaded', async () => {
    serve({code: 'not_found', message: 'no chunk'}, 404);
    renderReader();
    expect(
      await screen.findByText('The filing text could not be loaded.'),
    ).toBeInTheDocument();
  });

  it('closes on a click on the backdrop', async () => {
    serve(CONTEXT_1);
    const {onClose} = renderReader();
    await screen.findByTestId('reader-mark');
    fireEvent.click(screen.getByTestId('filing-reader'));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('filing-reader-backdrop'));
    expect(onClose).toHaveBeenCalled();
  });

  it('keeps Tab inside the dialog and focuses Close on open', async () => {
    serve(CONTEXT_1);
    renderReader();
    await screen.findByTestId('reader-mark');
    const close = screen.getByTestId('reader-close');
    expect(close).toHaveFocus();
    const link = screen.getByTestId('sec-link');
    link.focus();
    fireEvent.keyDown(window, {key: 'Tab'});
    expect(screen.getByTestId('reader-next')).toHaveFocus();
    fireEvent.keyDown(window, {key: 'Tab', shiftKey: true});
    expect(link).toHaveFocus();
  });
});
