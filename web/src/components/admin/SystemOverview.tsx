import type {JSX} from 'react';

import type {SystemResponse} from '../../api/types';
import {bytes, usd, when} from '../../lib/format';
import {OpsPanelHead} from './OpsPanelHead';
import type {Stat} from './StatList';
import {StatList} from './StatList';

/** Props of SystemOverview. */
export interface SystemOverviewProps {
  readonly system: SystemResponse;
}

/**
 * The service, the index build, the corpus inventory (`keel inventory`),
 * the budget, and the scheduler of the system page, as 4 stat panels.
 *
 * @param props The props.
 * @return The panels.
 */
export function SystemOverview({system}: SystemOverviewProps): JSX.Element {
  const {index, inventory, budget, scheduler} = system;
  const service: Stat[] = [
    {label: 'version', value: system.version},
    {label: 'provider', value: system.provider},
    {label: 'model', value: system.model},
    {
      label: 'mode',
      value: system.offline ? 'offline (answer cache only)' : 'online',
      ...(system.offline ? {tone: 'warn' as const} : {}),
    },
  ];
  if (budget !== null) {
    service.push({
      label: 'budget today',
      value: `${usd(budget.spent_usd)} of ${usd(budget.daily_usd)}${budget.stopped ? ', stopped' : ''}`,
      ...(budget.stopped ? {tone: 'down' as const} : {}),
    });
  }
  service.push({
    label: 'scheduler',
    value: scheduler.enabled
      ? `${scheduler.running ? 'running' : 'stopped'}, refresh ${scheduler.refresh_at}, backup ${scheduler.backup_at}, keep ${scheduler.backup_keep}`
      : 'off (KEEL_SCHEDULER__ENABLED=1 turns it on)',
  });
  for (const job of scheduler.jobs) {
    service.push({label: `next ${job.name}`, value: when(job.next_run)});
  }
  const counts = index.counts ?? {};
  const build: Stat[] = [
    {
      label: 'state',
      value: index.loaded
        ? index.verified === false
          ? 'loaded, not verified'
          : 'loaded'
        : 'not loaded',
      tone: index.loaded ? 'up' : 'down',
    },
    {label: 'index version', value: index.index_version ?? '--'},
    {label: 'build', value: index.build_id ?? '--'},
    {label: 'built', value: when(index.built_at)},
    {
      label: 'filings',
      value: `${index.filings ?? '--'} indexed, ${index.quarantined ?? 0} quarantined`,
    },
    {
      label: 'chunks',
      value: `${counts['chunks'] ?? '--'} (${counts['table_chunks'] ?? 0} tables)`,
    },
    {
      label: 'corpus checksum',
      value:
        index.corpus_checksum_match === null
          ? '--'
          : index.corpus_checksum_match
            ? 'matches the build'
            : (index.corpus_note ?? 'differs from the build'),
      ...(index.corpus_checksum_match === false ? {tone: 'warn' as const} : {}),
    },
  ];
  if (index.error !== null) {
    build.push({label: 'error', value: index.error, tone: 'down'});
  }
  const corpus: Stat[] =
    inventory.error !== undefined
      ? [{label: 'error', value: inventory.error, tone: 'down'}]
      : [
          {
            label: 'files',
            value: `${inventory.file_count ?? '--'} (${bytes(inventory.total_bytes)})`,
          },
          {label: 'tickers', value: String(inventory.ticker_count ?? '--')},
          {
            label: 'forms',
            value: Object.entries(inventory.form_counts ?? {})
              .map(([form, n]) => `${form} ${n}`)
              .join(', '),
          },
          {
            label: 'filed',
            value: `${inventory.first_filing ?? '--'} to ${inventory.last_filing ?? '--'}`,
          },
          {
            label: 'manifest',
            value: inventory.manifest_present ? 'present' : 'absent',
          },
          {
            label: 'discrepancies',
            value: String(inventory.discrepancy_count ?? 0),
            ...((inventory.discrepancy_count ?? 0) > 0
              ? {tone: 'warn' as const}
              : {}),
          },
        ];
  return (
    <div className="grid items-start gap-3 md:grid-cols-3">
      <section className="panel" aria-label="Service" data-testid="sys-service">
        <OpsPanelHead title="Service" />
        <StatList stats={service} />
      </section>
      <section className="panel" aria-label="Index" data-testid="sys-index">
        <OpsPanelHead title="Index" />
        <StatList stats={build} />
      </section>
      <section
        className="panel"
        aria-label="Corpus inventory"
        data-testid="sys-inventory"
      >
        <OpsPanelHead title="Corpus" note="keel inventory" />
        <StatList stats={corpus} />
        {(inventory.discrepancies ?? []).length > 0 && (
          <ul className="border-t border-line px-3 py-2 text-[11.5px] text-ink-2">
            {(inventory.discrepancies ?? []).map(item => (
              <li key={item} className="break-words">
                {item}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
