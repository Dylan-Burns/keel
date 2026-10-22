import type {JSX} from 'react';
import {useEffect, useState} from 'react';

import {fetchAudit} from '../../api/admin';
import type {AuditItem} from '../../api/types';
import {scalar, when} from '../../lib/format';
import {OpsPanelHead} from './OpsPanelHead';

/** Props of AuditPanel. */
export interface AuditPanelProps {
  /** A counter the page bumps to reload the rows. */
  readonly version: number;
}

/** The load state of the rows. */
type Load =
  | {readonly kind: 'loading'}
  | {readonly kind: 'error'; readonly message: string}
  | {readonly kind: 'ready'; readonly items: readonly AuditItem[]};

/**
 * The admin audit (`GET /api/admin/audit`): every change and every refused
 * attempt, newest first.
 *
 * @param props The props.
 * @return The panel.
 */
export function AuditPanel({version}: AuditPanelProps): JSX.Element {
  const [load, setLoad] = useState<Load>({kind: 'loading'});
  useEffect(() => {
    let cancelled = false;
    fetchAudit(100)
      .then(list => {
        if (!cancelled) {
          setLoad({kind: 'ready', items: list.items});
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoad({kind: 'error', message: 'The admin audit could not load.'});
        }
      });
    return () => {
      cancelled = true;
    };
  }, [version]);
  return (
    <section className="panel" aria-label="Admin audit" data-testid="sys-audit">
      <OpsPanelHead title="Admin audit" note="newest first, 100 rows" />
      {load.kind === 'loading' && (
        <p className="panel-body text-[12px] text-muted">Loading the audit.</p>
      )}
      {load.kind === 'error' && (
        <p className="panel-body text-[12px] text-down" role="alert">
          {load.message}
        </p>
      )}
      {load.kind === 'ready' && load.items.length === 0 && (
        <p className="panel-body text-[12px] text-muted">
          No admin actions yet.
        </p>
      )}
      {load.kind === 'ready' && load.items.length > 0 && (
        <div className="max-h-[28rem] overflow-auto">
          <table className="grid-table" data-testid="audit-table">
            <thead className="sticky top-0">
              <tr>
                <th scope="col">At</th>
                <th scope="col">User</th>
                <th scope="col">Action</th>
                <th scope="col">Target</th>
                <th scope="col">Params</th>
                <th scope="col">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {load.items.map((item, index) => (
                <tr key={`${item.at}-${index}`} data-testid="audit-row">
                  <td className="num whitespace-nowrap text-[11.5px] text-ink-2">
                    {when(item.at)}
                  </td>
                  <td className="font-mono text-[11.5px]">{item.user}</td>
                  <td className="whitespace-nowrap font-mono text-[11.5px]">
                    {item.action}
                  </td>
                  <td className="font-mono text-[11.5px] text-ink-2">
                    {item.target ?? ''}
                  </td>
                  <td className="min-w-[10rem] font-mono text-[11px] text-muted [overflow-wrap:anywhere]">
                    {item.params === null
                      ? ''
                      : Object.entries(item.params)
                          .map(([k, v]) => `${k}=${scalar(v)}`)
                          .join(' ')}
                  </td>
                  <td>
                    <span
                      className={`tag ${item.outcome === 'ok' ? 'tag-up' : 'tag-warn'}`}
                    >
                      {item.outcome}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
