import type {JSX} from 'react';

import type {PromptVersion} from '../../api/types';
import {diffVersions} from '../../lib/promptDiff';
import type {PromptNote} from '../../lib/promptNotes';
import {noteFor} from '../../lib/promptNotes';
import {RuleChange} from './RuleChange';

/** Props of PromptChanges. */
export interface PromptChangesProps {
  /** The prompt versions, oldest first. */
  readonly prompts: readonly PromptVersion[];
}

const OUTCOME: Readonly<Record<PromptNote['outcome'], string>> = {
  first: 'First version',
  kept: 'Kept',
  rejected: 'Rejected',
};

/** The status tag of a version: in use, kept, rejected, or first. */
function Status({
  prompt,
  note,
}: {
  readonly prompt: PromptVersion;
  readonly note: PromptNote | null;
}): JSX.Element | null {
  if (prompt.current) {
    return <span className="tag tag-up">In use</span>;
  }
  if (note === null) {
    return null;
  }
  return (
    <span className={note.outcome === 'rejected' ? 'tag tag-down' : 'tag'}>
      {note.outcome === 'rejected' ? '✕ ' : ''}
      {OUTCOME[note.outcome]}
    </span>
  );
}

/**
 * The history of the answer prompt, newest first: per version what changed
 * and why in plain words, the measured result, and each changed rule before
 * and after. Rules whose meaning changed come first; rules only reworded
 * (to keep the prompt short) fold under them. The full text of the version
 * folds at the end.
 *
 * @param props The prompt versions.
 * @return The panel.
 */
export function PromptChanges({prompts}: PromptChangesProps): JSX.Element {
  const newestFirst = prompts
    .map((prompt, index) => ({prompt, previous: prompts[index - 1] ?? null}))
    .reverse();
  return (
    <section
      className="panel"
      aria-label="Prompt changes"
      data-testid="prompt-changes"
    >
      <div className="panel-head">
        <h2 className="panel-title">Prompt changes</h2>
        <span className="ml-auto font-mono text-[10.5px] text-muted">
          prompts/answer_system_v*.md
        </span>
      </div>
      <div className="panel-body space-y-2">
        <p className="text-[12.5px] text-ink-2">
          The prompt is the fixed instructions sent to the model with every
          question. Each version changes 1 thing, is measured on the test
          questions, and is kept only if the answers stay as faithful to the
          filings. Newest first.
        </p>
        {newestFirst.map(({prompt, previous}, index) => {
          const note = noteFor(prompt.version);
          const changes =
            previous === null ? [] : diffVersions(previous, prompt);
          const meaning = new Set(note?.meaning ?? changes.map(c => c.key));
          const major = changes.filter(c => meaning.has(c.key));
          const wording = changes.filter(c => !meaning.has(c.key));
          return (
            <details
              key={prompt.version}
              open={index === 0}
              className="rounded-sm border border-line"
              data-testid="prompt-version"
              data-version={prompt.version}
            >
              <summary className="flex cursor-pointer flex-wrap items-center gap-x-2.5 gap-y-1 px-3 py-2 hover:bg-raised">
                <span className="font-mono text-[13px] font-semibold text-ink">
                  {prompt.version}
                </span>
                <Status prompt={prompt} note={note} />
                <span className="text-[13px] text-ink">
                  {note?.title ?? 'See the prompt log for this version'}
                </span>
              </summary>
              <div className="space-y-3 border-t border-line px-3 py-3">
                {note !== null && (
                  <dl className="grid gap-x-4 gap-y-1.5 text-[12.5px] sm:grid-cols-[max-content_1fr]">
                    <dt className="font-semibold text-ink">What changed</dt>
                    <dd className="text-ink-2">{note.what}</dd>
                    <dt className="font-semibold text-ink">Why</dt>
                    <dd className="text-ink-2">{note.why}</dd>
                    <dt className="font-semibold text-ink">Result</dt>
                    <dd className="text-ink-2">{note.result}</dd>
                  </dl>
                )}
                {previous !== null && major.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="section-title">
                      Rules before and after ({previous.version} to{' '}
                      {prompt.version})
                    </h3>
                    {major.map(change => (
                      <RuleChange
                        key={change.key}
                        change={change}
                        from={previous.version}
                        to={prompt.version}
                      />
                    ))}
                  </div>
                )}
                {previous !== null && wording.length > 0 && (
                  <details data-testid="prompt-wording">
                    <summary className="cursor-pointer text-[12px] text-ink-2 hover:text-accent">
                      {wording.length} more{' '}
                      {wording.length === 1 ? 'part' : 'parts'} reworded with
                      the same meaning
                    </summary>
                    <div className="mt-2 space-y-2">
                      {wording.map(change => (
                        <RuleChange
                          key={change.key}
                          change={change}
                          from={previous.version}
                          to={prompt.version}
                        />
                      ))}
                    </div>
                  </details>
                )}
                {previous !== null && changes.length === 0 && (
                  <p className="text-[12.5px] text-muted">
                    The prompt text matches {previous.version}; the change is
                    outside the prompt files.
                  </p>
                )}
                <details>
                  <summary className="cursor-pointer text-[12px] text-ink-2 hover:text-accent">
                    Full prompt of {prompt.version}
                  </summary>
                  <div className="mt-2 space-y-2">
                    <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-sm border border-line bg-raised p-2.5 font-mono text-[11.5px] text-ink">
                      {prompt.system}
                    </pre>
                    {prompt.user !== null && (
                      <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-sm border border-line bg-raised p-2.5 font-mono text-[11.5px] text-ink">
                        {prompt.user}
                      </pre>
                    )}
                  </div>
                </details>
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}
