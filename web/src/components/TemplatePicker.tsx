import type {JSX} from 'react';
import {useEffect, useState} from 'react';

import {fetchTemplates} from '../api/client';
import type {QuestionTemplate} from '../api/types';
import {fillTemplate} from '../lib/templates';

/** Props of TemplatePicker. */
export interface TemplatePickerProps {
  /** False without a token: the templates need one to load. */
  readonly enabled: boolean;
  /** Puts the filled question in the question box; the user asks. */
  readonly onFill: (question: string) => void;
}

/**
 * The question templates of chapter 27.2: 5 buttons (public comparables,
 * risk benchmark, portfolio review, regulatory scan, memo paragraph). A
 * button opens 2 fields, the companies (names, tickers, or a comp set such
 * as `my software comps`) and the period; Fill puts the question in the
 * question box and sends nothing.
 *
 * @param props The props.
 * @return The picker, or nothing before the templates load.
 */
export function TemplatePicker({
  enabled,
  onFill,
}: TemplatePickerProps): JSX.Element | null {
  const [templates, setTemplates] = useState<readonly QuestionTemplate[]>([]);
  const [chosen, setChosen] = useState<QuestionTemplate | null>(null);
  const [companies, setCompanies] = useState('');
  const [period, setPeriod] = useState('');
  useEffect(() => {
    if (!enabled) {
      return;
    }
    let cancelled = false;
    fetchTemplates()
      .then(list => {
        if (!cancelled) {
          setTemplates(list.items);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setTemplates([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  if (!enabled || templates.length === 0) {
    return null;
  }
  const filled =
    chosen === null ? null : fillTemplate(chosen, companies, period);
  return (
    <section
      className="mt-2.5 space-y-2"
      aria-label="Question templates"
      data-testid="template-picker"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="section-title mr-1">Templates</span>
        {templates.map(template => (
          <button
            key={template.id}
            type="button"
            className="chip aria-pressed:border-accent aria-pressed:text-accent"
            aria-pressed={chosen?.id === template.id}
            data-testid="template-button"
            onClick={() =>
              setChosen(chosen?.id === template.id ? null : template)
            }
          >
            {template.label}
          </button>
        ))}
      </div>
      {chosen !== null && (
        <form
          className="flex flex-wrap items-end gap-2 border border-line bg-raised p-2"
          data-testid="template-form"
          onSubmit={event => {
            event.preventDefault();
            if (filled !== null) {
              onFill(filled);
              setChosen(null);
            }
          }}
        >
          <label className="flex flex-col gap-1">
            <span className="section-title">Companies</span>
            <input
              className="input w-64 max-w-full"
              value={companies}
              placeholder="Apple and Tesla, or my software comps"
              maxLength={300}
              data-testid="template-companies"
              onChange={event => setCompanies(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="section-title">Period</span>
            <input
              className="input w-48 max-w-full"
              value={period}
              placeholder={chosen.default_period}
              maxLength={300}
              data-testid="template-period"
              onChange={event => setPeriod(event.target.value)}
            />
          </label>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={filled === null}
            data-testid="template-fill"
          >
            Fill
          </button>
        </form>
      )}
    </section>
  );
}
