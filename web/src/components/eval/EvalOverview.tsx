import type {JSX} from 'react';

import type {EvalGate} from '../../api/types';
import type {ParsedReport, ReportTable} from '../../lib/evalReport';
import {column, tableOf} from '../../lib/evalReport';
import type {BarItem} from './BarList';
import {BarList} from './BarList';

/** Props of EvalOverview. */
export interface EvalOverviewProps {
  readonly report: ParsedReport;
  readonly gates: readonly EvalGate[];
}

/** 1 headline number. */
interface Tile {
  readonly label: string;
  readonly value: string;
  readonly note: string;
}

/** The cell of a named column in the row whose first cell is `key`. */
function cell(table: ReportTable | null, key: string, name: string): string {
  if (table === null) {
    return 'n/a';
  }
  const at = table.columns.indexOf(name);
  const row = table.rows.find(r => r[0] === key);
  return (at >= 0 ? row?.[at] : undefined) ?? 'n/a';
}

const two = (value: number): string => value.toFixed(2);

/** A round upper end for a scale of milliseconds. */
function niceMax(value: number): number {
  const step = 10 ** Math.floor(Math.log10(Math.max(value, 1)));
  return Math.ceil(value / step) * step;
}

/**
 * The top of the eval page: the headline numbers of the run, then charts of
 * the report tables. Each chart says in 1 sentence how to read it; the
 * tables of the report below hold the same numbers.
 *
 * @param props The parsed report and the gates.
 * @return The overview.
 */
export function EvalOverview({report, gates}: EvalOverviewProps): JSX.Element {
  const retrieval = tableOf(report, 'retrieval metrics');
  const answers = tableOf(report, 'answer metrics');
  const perAnswer = tableOf(report, 'per question (answers)');
  const ablation = tableOf(report, 'ablation');
  const gate = (name: string): EvalGate | undefined =>
    gates.find(g => g.name === name);
  const gateNote = (name: string): string => {
    const found = gate(name);
    return found === undefined ? '' : `; gate ${found.threshold_text}`;
  };
  const recallGate = gate('Recall at 25')?.threshold ?? null;
  const faithGate = gate('Faithfulness')?.threshold ?? null;
  const passed = gates.filter(g => g.passed === true).length;
  const failed = gates.filter(g => g.passed === false);
  const tiles: Tile[] = [
    {
      label: 'Gates passed',
      value: `${passed} of ${gates.length}`,
      note:
        failed.length === 0
          ? 'Release not blocked'
          : `Blocked by ${failed.map(g => g.name).join(', ')}`,
    },
    {
      label: 'Questions',
      value: report.run['Questions'] ?? 'n/a',
      note: `Golden set ${report.run['Golden set'] ?? 'n/a'}`,
    },
    {
      label: 'Search recall at 25',
      value: cell(retrieval, 'all', 'R@25'),
      note: `Share of the right passages found${gateNote('Recall at 25')}`,
    },
    {
      label: 'Faithfulness',
      value: cell(answers, 'all', 'Faithfulness'),
      note: `Share of statements the sources support${gateNote('Faithfulness')}`,
    },
    {
      label: 'Answer time, slow case',
      value: `${cell(answers, 'all', 'Latency p95 s')} s`,
      note: `95% of answers were faster${gateNote('Latency p95')}`,
    },
    {
      label: 'Cost per answer',
      value: `$${cell(answers, 'all', 'Mean cost USD')}`,
      note: `Mean model cost${gateNote('Mean cost per question')}`,
    },
  ];

  const byType: BarItem[] = column(retrieval, 'R@25')
    .filter(p => p.label !== 'all')
    .map(p => ({
      label: p.label,
      value: p.value,
      emphasis: recallGate !== null && p.value < recallGate,
    }));

  const typeAt = perAnswer?.columns.indexOf('Type') ?? -1;
  const faithful: BarItem[] = column(perAnswer, 'Faithfulness')
    .map(p => {
      const row = perAnswer?.rows.find(r => r[0] === p.label);
      const type = typeAt >= 0 ? row?.[typeAt] : undefined;
      return {
        label: p.label,
        value: p.value,
        emphasis: faithGate !== null && p.value < faithGate,
        ...(type === undefined ? {} : {detail: type}),
      };
    })
    .sort((a, b) => a.value - b.value);

  const inUse = (label: string): boolean => label === 'hybrid';
  const variantRecall: BarItem[] = column(ablation, 'R@25').map(p => ({
    label: p.label,
    value: p.value,
    emphasis: inUse(p.label),
  }));
  const variantTime: BarItem[] = column(ablation, 'Retrieval p50 ms').map(
    p => ({label: p.label, value: p.value, emphasis: inUse(p.label)}),
  );
  const timeMax = niceMax(Math.max(1, ...variantTime.map(i => i.value)));

  return (
    <section
      className="panel"
      aria-label="At a glance"
      data-testid="eval-overview"
    >
      <div className="panel-head">
        <h2 className="panel-title">At a glance</h2>
        <span className="ml-auto font-mono text-[10.5px] text-muted">
          {report.run['Run ID'] ?? ''}
        </span>
      </div>
      <div className="panel-body space-y-5">
        <ul
          className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6"
          data-testid="eval-tiles"
        >
          {tiles.map(tile => (
            <li
              key={tile.label}
              className="rounded-sm border border-line bg-raised px-3 py-2"
            >
              <div className="text-[11.5px] text-ink-2">{tile.label}</div>
              <div className="text-[22px] font-semibold leading-tight text-ink">
                {tile.value}
              </div>
              <div className="text-[11px] text-muted">{tile.note}</div>
            </li>
          ))}
        </ul>
        <div className="grid items-start gap-6 lg:grid-cols-2">
          <div className="space-y-6">
            {byType.length > 0 && (
              <BarList
                title="Search recall by question type"
                caption="How many of the right passages search found in its top 25, per kind of question. Bars left of the line miss the gate."
                items={byType}
                max={1}
                format={two}
                {...(recallGate === null
                  ? {}
                  : {
                      target: {
                        value: recallGate,
                        label: `Gate: ${two(recallGate)}`,
                      },
                    })}
                legend={{emphasis: 'Below the gate', rest: 'At or above'}}
                testId="chart-recall-type"
              />
            )}
            {variantRecall.length > 0 && (
              <BarList
                title="Search setups: accuracy"
                caption="Recall at 25 of each search setup on the same questions. Keel uses hybrid with the reranker."
                items={variantRecall}
                max={1}
                format={two}
                legend={{emphasis: 'In use (hybrid)', rest: 'Other setups'}}
                testId="chart-variant-recall"
              />
            )}
            {variantTime.length > 0 && (
              <BarList
                title="Search setups: speed"
                caption="The typical search time of each setup, in seconds. The reranker buys accuracy with time."
                items={variantTime}
                max={timeMax}
                format={value => `${(value / 1000).toFixed(2)} s`}
                tickFormat={value => `${(value / 1000).toFixed(1)} s`}
                legend={{emphasis: 'In use (hybrid)', rest: 'Other setups'}}
                testId="chart-variant-time"
              />
            )}
          </div>
          {faithful.length > 0 && (
            <BarList
              title="Faithfulness of each answer"
              caption="The share of each answer's statements its sources support, weakest first. Bars left of the line miss the gate."
              items={faithful}
              max={1}
              format={two}
              {...(faithGate === null
                ? {}
                : {
                    target: {
                      value: faithGate,
                      label: `Gate: ${two(faithGate)}`,
                    },
                  })}
              legend={{emphasis: 'Below the gate', rest: 'At or above'}}
              testId="chart-faithfulness"
            />
          )}
        </div>
      </div>
    </section>
  );
}
