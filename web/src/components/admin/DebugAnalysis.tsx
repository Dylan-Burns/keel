import type {JSX} from 'react';

import type {DebugUnderstand} from '../../api/types';
import {scalar} from '../../lib/format';
import {OpsPanelHead} from './OpsPanelHead';
import type {Stat} from './StatList';
import {StatList} from './StatList';

/** Props of DebugAnalysis. */
export interface DebugAnalysisProps {
  readonly analysis: DebugUnderstand;
}

/**
 * The question analysis of `keel understand`: the resolved companies with
 * the rule that found each, and the plan inputs (type, time scope, topic
 * terms, section weights, flags). Every value is a JSX text node.
 *
 * @param props The props.
 * @return The panel.
 */
export function DebugAnalysis({analysis}: DebugAnalysisProps): JSX.Element {
  const scope = analysis.time_scope;
  const raised = Object.entries(analysis.flags)
    .filter(([, on]) => on)
    .map(([flag]) => flag);
  const plan: Stat[] = [
    {label: 'primary type', value: analysis.primary_type},
    {label: 'types', value: analysis.types.join(', ')},
    {
      label: 'time scope',
      value: [
        scope.kind,
        scope.fiscal_year === null ? '' : `FY${scope.fiscal_year}`,
        scope.fiscal_period ?? '',
      ]
        .filter(Boolean)
        .join(' '),
    },
    {
      label: 'topic terms',
      value: analysis.topic_terms.join(', ') || 'none',
    },
    {
      label: 'section weights',
      value:
        Object.entries(analysis.section_weights)
          .map(([section, weight]) => `${section} ${weight}`)
          .join(', ') || 'none',
    },
    {label: 'flags', value: raised.join(', ') || 'none'},
    {label: 'comp sets', value: scalar(analysis.comp_sets) || 'none'},
    {label: 'not indexed', value: scalar(analysis.not_indexed) || 'none'},
    {label: 'elapsed', value: `${analysis.elapsed_ms.toFixed(1)} ms`},
  ];
  if (analysis.out_of_scope_reason !== null) {
    plan.push({
      label: 'out of scope',
      value: analysis.out_of_scope_reason,
      tone: 'warn',
    });
  }
  return (
    <section
      className="panel"
      aria-label="Question analysis"
      data-testid="debug-analysis"
    >
      <OpsPanelHead title="Understanding" note="keel understand" />
      {analysis.entities.length === 0 ? (
        <p className="panel-body text-[12px] text-muted">
          No company resolved.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="grid-table" data-testid="debug-entities">
            <thead>
              <tr>
                <th scope="col">Ticker</th>
                <th scope="col">Company</th>
                <th scope="col">Matched text</th>
                <th scope="col">Rule</th>
              </tr>
            </thead>
            <tbody>
              {analysis.entities.map(entity => (
                <tr key={`${entity.ticker}-${entity.text}`}>
                  <td className="font-mono text-accent">{entity.ticker}</td>
                  <td>{entity.company}</td>
                  <td className="font-mono text-[11.5px]">{entity.text}</td>
                  <td className="font-mono text-[11.5px] text-ink-2">
                    {entity.rule}
                    {entity.fuzzy && entity.score !== null
                      ? ` (fuzzy ${entity.score})`
                      : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <StatList stats={plan} testId="debug-plan" />
    </section>
  );
}
