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
      className="panel mx-auto mt-16 max-w-lg space-y-3 p-5 text-[13px]"
      data-testid="card-index-not-built"
    >
      <h2 className="panel-title text-[12px]">The index is not built</h2>
      <p>Build it once from the corpus, then reload the page:</p>
      <pre className="overflow-x-auto border border-line bg-field px-3 py-2 font-mono text-[12px] text-up">
        uv run keel index
      </pre>
      <p className="text-muted">
        The full build takes several minutes on a laptop CPU.
      </p>
      <button type="button" className="btn btn-primary" onClick={onRecheck}>
        Check again
      </button>
    </section>
  );
}
