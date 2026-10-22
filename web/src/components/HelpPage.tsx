import type {JSX} from 'react';

/** The date the backup restore was last tested (infra/README.md). */
export const RESTORE_TESTED_ON = '2026-10-22';

/** The months the pilot keeps the audit log (chapter 27.2). */
export const AUDIT_RETENTION_MONTHS = 12;

/** 1 section of the data use page. */
export interface Section {
  readonly id: string;
  readonly title: string;
  readonly lines: readonly string[];
}

/** The sections of the data use page, in reading order. */
export const DATA_USE_SECTIONS: readonly Section[] = [
  {
    id: 'model-provider',
    title: 'What goes to the model provider',
    lines: [
      'Each question makes exactly 1 request to the Anthropic API.',
      'The request holds the question, the filing excerpts that retrieval picked from the index, for a numeric question the SEC company facts lines of the companies in it, and the fixed instructions of the prompt.',
      'It holds no token, no user name, and no earlier question.',
      'Under its commercial terms, Anthropic does not use API inputs or outputs to train its models. The engineer checks the current terms before the pilot starts.',
    ],
  },
  {
    id: 'sec-edgar',
    title: 'What goes to SEC EDGAR',
    lines: [
      'The service fetches public documents from www.sec.gov and data.sec.gov: the ticker map, the company facts, the list of filings of a company, and the filing documents that keel add and the nightly refresh ingest.',
      'Each request carries the contact name and email address that the SEC requires. No question and no answer goes to the SEC.',
      'The other outbound requests are made by the operator setup, never with a question: the first start downloads the corpus and the index archive from GitHub or the configured corpus URL, and the embedding models from Hugging Face when the host has no copy yet.',
    ],
  },
  {
    id: 'logs',
    title: 'What the service logs',
    lines: [
      'The audit log holds 1 line per question: the request ID, the time, the user name, the question, the tickers, the IDs of the filing excerpts sent, the prompt version and hash, the index version, the model, the token counts, the cost, and the latency.',
      'It never holds the prompt text, an API key, or a token. The users file keeps only the sha256 of each token.',
      'The answer cache keeps each cached question with its full answer, so a repeat answers at once. The pilot store keeps the comp sets and the feedback votes and notes with the user name.',
      `The pilot keeps the audit log, the answer cache, and the feedback for ${AUDIT_RETENTION_MONTHS} months. The engineer deletes older entries; the service does not delete them on its own.`,
    ],
  },
  {
    id: 'history',
    title: 'Who can see the history',
    lines: [
      'Each user sees their own questions on the history page. An admin can also see every user.',
      'A shareable link opens 1 stored answer, read-only, for anyone with a token. The page does not show who asked it.',
    ],
  },
  {
    id: 'backups',
    title: 'Backups and restore',
    lines: [
      'When the nightly scheduler is on, it writes a checksummed archive of the index and the logs (the audit log included) to the backup directory on the host volume, and keeps the newest 7.',
      `The restore procedure was last tested on ${RESTORE_TESTED_ON}.`,
    ],
  },
];

/**
 * The data use page (chapter 27.2): what Keel sends where, what it logs and
 * for how long, who sees the history, and the date of the restore test.
 * External names are text, not links.
 *
 * @return The page.
 */
export function HelpPage(): JSX.Element {
  return (
    <div
      className="min-h-screen bg-paper font-sans text-ink"
      data-testid="help-page"
    >
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
        <h1 className="text-lg font-semibold">Data use</h1>
        <button
          type="button"
          className="text-sm text-accent underline"
          onClick={() => window.location.assign('/')}
        >
          Back to questions
        </button>
      </header>
      <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6">
        {DATA_USE_SECTIONS.map(section => (
          <section
            key={section.id}
            aria-labelledby={`help-${section.id}`}
            data-testid={`help-${section.id}`}
            className="space-y-2"
          >
            <h2 id={`help-${section.id}`} className="text-base font-semibold">
              {section.title}
            </h2>
            {section.lines.map(line => (
              <p key={line} className="text-sm text-slate-700">
                {line}
              </p>
            ))}
          </section>
        ))}
      </main>
    </div>
  );
}
