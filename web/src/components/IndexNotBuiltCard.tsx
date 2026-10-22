import type {JSX} from 'react';

/** Props of IndexNotBuiltCard. */
export interface IndexNotBuiltCardProps {
  readonly onRecheck: () => void;
}

/**
 * The full-page index-not-built card with the build command (E-F-01).
 *
 * @param props The props.
 * @return The card.
 */
export function IndexNotBuiltCard({
  onRecheck,
}: IndexNotBuiltCardProps): JSX.Element {
  return (
    <section
      className="mx-auto mt-16 max-w-lg space-y-3 rounded-xl border border-slate-300 bg-white p-6 text-sm shadow"
      data-testid="card-index-not-built"
    >
      <h2 className="text-lg font-medium">The index is not built</h2>
      <p>Build it once from the corpus, then reload the page:</p>
      <pre className="rounded bg-slate-900 px-3 py-2 font-mono text-slate-100">
        uv run keel index
      </pre>
      <p className="text-slate-600">
        The full build takes several minutes on a laptop CPU.
      </p>
      <button
        type="button"
        className="rounded bg-ink px-3 py-1 text-white"
        onClick={onRecheck}
      >
        Check again
      </button>
    </section>
  );
}
