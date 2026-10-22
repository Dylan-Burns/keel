import {fireEvent, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {FeedbackBar} from './FeedbackBar';

function serve(status = 200): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((_path: string, init: RequestInit) => {
    const body = JSON.parse(String(init.body)) as {vote: string};
    return Promise.resolve(
      status === 200
        ? new Response(
            JSON.stringify({
              request_id: 'req-1',
              vote: body.vote,
              note: null,
              user: 'alice',
            }),
          )
        : new Response('{"detail":{"code":"not_found","message":"no"}}', {
            status,
          }),
    );
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('FeedbackBar', () => {
  it('sends a thumbs vote with the request ID', async () => {
    const fetchMock = serve();
    render(<FeedbackBar requestId="req-1" />);
    expect(screen.getByTestId('feedback-send-note')).toBeDisabled();
    fireEvent.click(screen.getByTestId('feedback-up'));
    expect(await screen.findByText('Thanks: vote saved.')).toBeInTheDocument();
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe('/api/feedback');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({
      request_id: 'req-1',
      vote: 'up',
      note: null,
    });
    expect(screen.getByTestId('feedback-up')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('sends the note with a thumbs-down vote and flags the answer', async () => {
    const fetchMock = serve();
    render(<FeedbackBar requestId="req-1" />);
    fireEvent.change(screen.getByTestId('feedback-note'), {
      target: {value: '  wrong fiscal year '},
    });
    fireEvent.click(screen.getByTestId('feedback-down'));
    expect(
      await screen.findByText('Thanks: flagged for review.'),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('feedback-send-note'));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const init = fetchMock.mock.calls[1]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toMatchObject({
      vote: 'down',
      note: 'wrong fiscal year',
    });
  });

  it('says when the vote fails', async () => {
    serve(404);
    render(<FeedbackBar requestId="req-1" />);
    fireEvent.click(screen.getByTestId('feedback-down'));
    expect(
      await screen.findByText('The vote could not be saved.'),
    ).toBeInTheDocument();
  });
});
