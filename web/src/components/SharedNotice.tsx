import type {JSX} from 'react';

import type {SharedLoad} from '../useKeel';

/** Props of SharedNotice. */
export interface SharedNoticeProps {
  /** The load state of the shared answer; `none` renders nothing. */
  readonly load: SharedLoad;
  readonly requestId: string;
}

const TEXT: Readonly<Record<Exclude<SharedLoad, 'none'>, string>> = {
  loading: 'Opening a shared answer.',
  loaded: 'A shared answer, read only. Ask a question above for a new answer.',
  missing:
    'This answer is no longer stored. The history page can ask the question again.',
};

/**
 * The line above a stored answer opened by its shareable link
 * `/a/{request_id}` (chapter 27.2): the answer renders read-only, or the
 * link names an answer that no store holds any more.
 *
 * @param props The props.
 * @return The notice, or null on any other route.
 */
export function SharedNotice({
  load,
  requestId,
}: SharedNoticeProps): JSX.Element | null {
  if (load === 'none') {
    return null;
  }
  return (
    <p
      className={`notice text-[13px] ${load === 'missing' ? 'notice-warn' : ''}`}
      role={load === 'missing' ? 'alert' : 'status'}
      data-testid="shared-notice"
      data-load={load}
    >
      {TEXT[load]} <span className="num text-xs text-muted">{requestId}</span>
    </p>
  );
}
