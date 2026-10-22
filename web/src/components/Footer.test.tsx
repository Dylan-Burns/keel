import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {Footer} from './Footer';

describe('Footer', () => {
  it('shows the request ID and the prompt version, and runs copy and export', () => {
    const onCopy = vi.fn();
    const onExport = vi.fn();
    const onShare = vi.fn();
    const onMemo = vi.fn();
    render(
      <Footer
        requestId="r-1"
        promptVersion="1.0.0"
        hasAnswer
        copyStatus="Copied"
        onCopy={onCopy}
        onExport={onExport}
        canShare
        onShare={onShare}
        onMemo={onMemo}
      />,
    );
    expect(screen.getByTestId('request-id')).toHaveTextContent('request r-1');
    expect(screen.getByTestId('prompt-version')).toHaveTextContent(
      'prompt 1.0.0',
    );
    fireEvent.click(screen.getByRole('button', {name: 'Copy as markdown'}));
    fireEvent.click(screen.getByRole('button', {name: 'Export JSON'}));
    expect(onCopy).toHaveBeenCalledOnce();
    expect(onExport).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByTestId('share-link'));
    expect(onShare).toHaveBeenCalledOnce();
    expect(screen.getByRole('status')).toHaveTextContent('Copied');
    fireEvent.click(screen.getByRole('button', {name: 'Memo .md'}));
    fireEvent.click(screen.getByRole('button', {name: 'Memo .docx'}));
    expect(onMemo.mock.calls).toEqual([['markdown'], ['docx']]);
  });

  it('turns the buttons off without an answer', () => {
    render(
      <Footer
        requestId={null}
        promptVersion={null}
        hasAnswer={false}
        copyStatus={null}
        onCopy={vi.fn()}
        onExport={vi.fn()}
        canShare={false}
        onShare={vi.fn()}
        onMemo={vi.fn()}
      />,
    );
    expect(
      screen.getByRole('button', {name: 'Copy as markdown'}),
    ).toBeDisabled();
    expect(screen.getByTestId('share-link')).toBeDisabled();
    expect(screen.getByTestId('memo-markdown')).toBeDisabled();
    expect(screen.getByTestId('memo-docx')).toBeDisabled();
  });

  it('opens the history page and the data use page', () => {
    const assign = vi.fn();
    vi.stubGlobal('location', {...window.location, assign});
    render(
      <Footer
        requestId={null}
        promptVersion={null}
        hasAnswer={false}
        copyStatus={null}
        onCopy={vi.fn()}
        onExport={vi.fn()}
        canShare={false}
        onShare={vi.fn()}
        onMemo={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId('history-link'));
    expect(assign).toHaveBeenCalledWith('/history');
    fireEvent.click(screen.getByTestId('compsets-link'));
    expect(assign).toHaveBeenCalledWith('/compsets');
    fireEvent.click(screen.getByTestId('help-link'));
    expect(assign).toHaveBeenCalledWith('/help');
    vi.unstubAllGlobals();
  });

  it('shows the admin links only to an admin', () => {
    const props = {
      requestId: null,
      promptVersion: null,
      hasAnswer: false,
      copyStatus: null,
      onCopy: vi.fn(),
      onExport: vi.fn(),
      canShare: false,
      onShare: vi.fn(),
      onMemo: vi.fn(),
    };
    const {rerender} = render(<Footer {...props} />);
    expect(screen.getByTestId('companies-link')).toBeInTheDocument();
    expect(screen.getByTestId('debug-link')).toBeInTheDocument();
    expect(screen.queryByTestId('jobs-link')).toBeNull();
    expect(screen.queryByTestId('users-link')).toBeNull();
    expect(screen.queryByTestId('system-link')).toBeNull();
    rerender(<Footer {...props} isAdmin />);
    expect(screen.getByTestId('jobs-link')).toBeInTheDocument();
    expect(screen.getByTestId('users-link')).toBeInTheDocument();
    expect(screen.getByTestId('system-link')).toBeInTheDocument();
  });
});
