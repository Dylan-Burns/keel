import type {JSX} from 'react';

/** Props of StaleIndexBanner. */
export interface StaleIndexBannerProps {
  readonly warnings: readonly string[];
}

/**
 * The amber stale-index banner: the corpus changed after the build, and the
 * rebuild command. The index still serves (E-F-02).
 *
 * @param props The props.
 * @return The banner.
 */
export function StaleIndexBanner({
  warnings,
}: StaleIndexBannerProps): JSX.Element {
  return (
    <div
      role="status"
      className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900"
      data-testid="banner-stale-index"
    >
      <strong className="font-medium">Stale index.</strong> The corpus changed
      after the index build. Rebuild with{' '}
      <code className="font-mono">uv run keel index --incremental</code>.
      {warnings.length > 0 && (
        <span className="ml-1 text-amber-800">{warnings.join(' ')}</span>
      )}
    </div>
  );
}
