import type {JSX} from 'react';

/**
 * The red offline banner from the browser `offline` event. The last answer
 * stays on screen (table 14.6).
 *
 * @return The banner.
 */
export function OfflineBanner(): JSX.Element {
  return (
    <div
      role="alert"
      className="border-b border-red-300 bg-red-50 px-4 py-2 text-sm text-red-900"
      data-testid="banner-offline"
    >
      <strong className="font-medium">Offline.</strong> The browser cannot reach
      the service. The last answer stays on screen.
    </div>
  );
}
