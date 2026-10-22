import type {JSX} from 'react';
import {useRef, useState} from 'react';

import {backupPath} from '../../api/admin';
import type {BackupList, Job} from '../../api/types';
import {downloadFile} from '../../lib/download';
import {bytes, when} from '../../lib/format';
import {JobFeedback} from './JobFeedback';
import {OpsPanelHead} from './OpsPanelHead';
import {TypedConfirm} from './TypedConfirm';
import {useJobLauncher} from './useJobLauncher';

/**
 * The size above which the page warns that the browser holds the whole
 * archive in memory before it saves it.
 */
export const LARGE_ARCHIVE = 200 * 1024 * 1024;

/** Props of BackupsPanel. */
export interface BackupsPanelProps {
  readonly backups: BackupList;
  /** Called when a backup or restore job ends, to reload the page. */
  readonly onDone: (job: Job) => void;
}

/**
 * The backups (`keel backup`, `keel restore`): the archives with their
 * size, time, and checksum, a download through the token, Back up now
 * (with an index-only option), and Restore behind a typed confirmation of
 * the exact archive name, which the API checks again.
 *
 * @param props The props.
 * @return The panel.
 */
export function BackupsPanel({
  backups,
  onDone,
}: BackupsPanelProps): JSX.Element {
  const {state, launch} = useJobLauncher();
  const [indexOnly, setIndexOnly] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const backupNow = useRef<HTMLButtonElement>(null);
  const onDownload = (name: string, size: number): void => {
    setNotice(
      size > LARGE_ARCHIVE
        ? `Downloading ${name} (${bytes(size)}): the browser holds it in memory first; for a large archive prefer curl or the host.`
        : `Downloading ${name}.`,
    );
    downloadFile(backupPath(name), name)
      .then(saved => setNotice(`Saved ${saved}.`))
      .catch(() => setNotice(`${name} could not be downloaded.`));
  };
  return (
    <section className="panel" aria-label="Backups" data-testid="sys-backups">
      <OpsPanelHead title="Backups" note="keel backup | keel restore ARCHIVE" />
      <div className="panel-body space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className="btn btn-primary"
            disabled={state.kind === 'sending'}
            ref={backupNow}
            data-testid="backup-now"
            onClick={() =>
              launch({kind: 'backup', params: {index_only: indexOnly}})
            }
          >
            Back up now
          </button>
          <label className="flex items-center gap-2 text-[12.5px] text-ink-2">
            <input
              type="checkbox"
              className="h-4 w-4 accent-[var(--k-accent)]"
              checked={indexOnly}
              onChange={event => setIndexOnly(event.target.checked)}
            />
            Index only (leave out the audit log and the pilot store)
          </label>
        </div>
        <p className="break-all font-mono text-[11px] text-muted">
          {backups.directory}
        </p>
        {restoring !== null && (
          <TypedConfirm
            key={restoring}
            title="Restore a backup"
            expected={restoring}
            actionLabel="Restore"
            testId="restore-confirm"
            onCancel={() => {
              setRestoring(null);
              backupNow.current?.focus();
            }}
            onConfirm={typed => {
              setRestoring(null);
              launch({
                kind: 'restore',
                params: {archive: typed},
                confirm: typed,
              });
            }}
          >
            The archive replaces the index build in service; the current build
            stays as <code className="font-mono">previous</code>. Questions keep
            the current build until the restored one loads.
          </TypedConfirm>
        )}
        {notice !== null && (
          <p className="font-mono text-[12px] text-ink-2" role="status">
            {notice}
          </p>
        )}
        <JobFeedback state={state} onFinal={onDone} />
        {backups.items.length === 0 ? (
          <p className="text-[12px] text-muted" data-testid="backups-empty">
            No archives in the backup directory yet.
          </p>
        ) : (
          <ul
            className="divide-y divide-line border border-line"
            aria-label="Backup archives"
            data-testid="backups-table"
          >
            {backups.items.map(item => (
              <li
                key={item.name}
                className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-2.5 py-2 odd:bg-raised"
                data-testid="backup-row"
                data-name={item.name}
              >
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[12px] font-semibold text-ink [overflow-wrap:anywhere]">
                    {item.name}
                  </p>
                  <p className="num text-[11px] text-muted">
                    {bytes(item.size_bytes)} · {when(item.created_at)} ·{' '}
                    <span title={item.sha256 ?? undefined}>
                      sha256{' '}
                      {item.sha256 === null ? '--' : item.sha256.slice(0, 12)}
                    </span>
                  </p>
                </div>
                <span className="flex gap-1.5">
                  <button
                    type="button"
                    className="btn"
                    aria-label={`Download ${item.name}`}
                    data-testid="backup-download"
                    onClick={() => onDownload(item.name, item.size_bytes)}
                  >
                    Download
                  </button>
                  <button
                    type="button"
                    className="btn"
                    aria-label={`Restore ${item.name}`}
                    data-testid="backup-restore"
                    onClick={() => setRestoring(item.name)}
                  >
                    Restore
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
