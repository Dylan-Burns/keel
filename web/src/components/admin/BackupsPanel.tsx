import type {JSX} from 'react';
import {useState} from 'react';

import {backupPath} from '../../api/admin';
import type {BackupList, Job} from '../../api/types';
import {downloadFile} from '../../lib/download';
import {bytes, when} from '../../lib/format';
import {JobFeedback} from './JobFeedback';
import {OpsPanelHead} from './OpsPanelHead';
import {TypedConfirm} from './TypedConfirm';
import {useJobLauncher} from './useJobLauncher';

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
  const onDownload = (name: string): void => {
    setNotice(`Downloading ${name}.`);
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
            onCancel={() => setRestoring(null)}
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
          <div className="overflow-x-auto border border-line">
            <table className="grid-table" data-testid="backups-table">
              <thead>
                <tr>
                  <th scope="col">Archive</th>
                  <th scope="col" className="text-right">
                    Size
                  </th>
                  <th scope="col">Created</th>
                  <th scope="col">SHA-256</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {backups.items.map(item => (
                  <tr
                    key={item.name}
                    data-testid="backup-row"
                    data-name={item.name}
                  >
                    <td className="whitespace-nowrap font-mono text-[11.5px]">
                      {item.name}
                    </td>
                    <td className="cell-num text-[11.5px]">
                      {bytes(item.size_bytes)}
                    </td>
                    <td className="num whitespace-nowrap text-[11.5px] text-ink-2">
                      {when(item.created_at)}
                    </td>
                    <td
                      className="num text-[11px] text-muted"
                      title={item.sha256 ?? undefined}
                    >
                      {item.sha256 === null ? '--' : item.sha256.slice(0, 12)}
                    </td>
                    <td>
                      <span className="flex justify-end gap-1.5">
                        <button
                          type="button"
                          className="btn"
                          aria-label={`Download ${item.name}`}
                          data-testid="backup-download"
                          onClick={() => onDownload(item.name)}
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
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
