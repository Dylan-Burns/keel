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

  it('hides until a question has an answer', () => {
    const {container} = render(
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
    expect(container).toBeEmptyDOMElement();
  });

  it('keeps the memo and share buttons off until the answer is stored', () => {
    render(
      <Footer
        requestId={null}
        promptVersion={null}
        hasAnswer
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
    ).toBeEnabled();
    expect(screen.getByTestId('share-link')).toBeDisabled();
    expect(screen.getByTestId('memo-markdown')).toBeDisabled();
    expect(screen.getByTestId('memo-docx')).toBeDisabled();
    expect(screen.queryByTestId('history-link')).toBeNull();
  });
});
