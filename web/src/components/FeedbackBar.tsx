import type {JSX} from 'react';
import {useState} from 'react';

import {sendFeedback} from '../api/client';
import type {Vote} from '../api/types';

/** Props of FeedbackBar. */
export interface FeedbackBarProps {
  /** The request ID of the finished answer. */
  readonly requestId: string;
}

/** The send state of the bar. */
type Status =
  | {readonly kind: 'idle'}
  | {readonly kind: 'sending'}
  | {readonly kind: 'saved'; readonly vote: Vote}
  | {readonly kind: 'failed'};

/**
 * The thumbs vote and the note on 1 answer (chapter 27.2). A vote is
 * stored at once; the note goes with the next vote or with Send note. A
 * thumbs-down vote flags the answer for the weekly review of candidate
 * golden questions. A new vote replaces the user's earlier one.
 *
 * @param props The props.
 * @return The bar.
 */
export function FeedbackBar({requestId}: FeedbackBarProps): JSX.Element {
  const [vote, setVote] = useState<Vote | null>(null);
  const [note, setNote] = useState('');
  const [status, setStatus] = useState<Status>({kind: 'idle'});
  const send = (chosen: Vote): void => {
    setVote(chosen);
    setStatus({kind: 'sending'});
    const text = note.trim();
    sendFeedback(requestId, chosen, text === '' ? null : text)
      .then(saved => setStatus({kind: 'saved', vote: saved.vote}))
      .catch(() => setStatus({kind: 'failed'}));
  };
  const button = (value: Vote, label: string, symbol: string): JSX.Element => (
    <button
      type="button"
      className={`rounded border px-2 py-1 ${
        vote === value ? 'border-accent bg-accent/10' : 'border-slate-300'
      }`}
      aria-label={label}
      aria-pressed={vote === value}
      disabled={status.kind === 'sending'}
      data-testid={`feedback-${value}`}
      onClick={() => send(value)}
    >
      {symbol}
    </button>
  );
  return (
    <div
      className="flex flex-wrap items-center gap-2 text-sm"
      data-testid="feedback-bar"
    >
      <span className="text-slate-500">Was this answer useful?</span>
      {button('up', 'Thumbs up', '\u{1F44D}')}
      {button('down', 'Thumbs down', '\u{1F44E}')}
      <input
        className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1"
        value={note}
        placeholder="Optional note (what is wrong or missing)"
        maxLength={2000}
        aria-label="Feedback note"
        data-testid="feedback-note"
        onChange={event => setNote(event.target.value)}
      />
      <button
        type="button"
        className="rounded border border-slate-300 px-2 py-1 disabled:border-slate-200 disabled:text-slate-400"
        disabled={vote === null || status.kind === 'sending'}
        data-testid="feedback-send-note"
        onClick={() => {
          if (vote !== null) {
            send(vote);
          }
        }}
      >
        Send note
      </button>
      <span role="status" data-testid="feedback-status">
        {status.kind === 'saved' &&
          (status.vote === 'down'
            ? 'Thanks: flagged for review.'
            : 'Thanks: vote saved.')}
        {status.kind === 'failed' && 'The vote could not be saved.'}
      </span>
    </div>
  );
}
