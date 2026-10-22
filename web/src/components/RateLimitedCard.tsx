import type {JSX} from 'react';

/** Props of RateLimitedCard. */
export interface RateLimitedCardProps {
  readonly secondsLeft: number;
}

/**
 * The rate-limited card: the wait from `retry_after` with a countdown. The
 * Ask button stays off until the countdown ends (table 14.6).
 *
 * @param props The props.
 * @return The card.
 */
export function RateLimitedCard({
  secondsLeft,
}: RateLimitedCardProps): JSX.Element {
  return (
    <section
      role="status"
      className="notice notice-warn space-y-1 text-[13px]"
      data-testid="card-rate-limited"
    >
      <h2 className="panel-title">Too many questions</h2>
      <p>
        Ask again in{' '}
        <span className="num font-semibold text-warn" data-testid="countdown">
          {secondsLeft}
        </span>{' '}
        s.
      </p>
    </section>
  );
}
