/**
 * The question templates of chapter 27.2: the picker fills `{companies}`
 * and `{period}` the way `keel.templates.fill` does on the server.
 */
import type {QuestionTemplate} from '../api/types';

/** The longest value of a template field, as on the server. */
export const MAX_VALUE_CHARS = 300;

const COMPANIES = '{companies}';
const PERIOD = '{period}';

/**
 * Collapses the white space of a field.
 *
 * @param text The field as typed.
 * @return The text with single spaces, trimmed.
 */
function squash(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(' ');
}

/**
 * Fills a template into a question. A value is plain text: a brace in a
 * value never opens another placeholder.
 *
 * @param template The template.
 * @param companies Company names, tickers, or a comp set phrase.
 * @param period The time scope; empty takes the default period.
 * @return The question, or null when the companies field is empty or a
 *     field is longer than 300 characters.
 */
export function fillTemplate(
  template: QuestionTemplate,
  companies: string,
  period: string,
): string | null {
  const names = squash(companies);
  const scope = squash(period) || template.default_period;
  if (
    names === '' ||
    names.length > MAX_VALUE_CHARS ||
    scope.length > MAX_VALUE_CHARS
  ) {
    return null;
  }
  const at = template.text.indexOf(COMPANIES);
  if (at < 0) {
    return null;
  }
  const head = template.text.slice(0, at).split(PERIOD).join(scope);
  const tail = template.text
    .slice(at + COMPANIES.length)
    .split(PERIOD)
    .join(scope);
  return `${head}${names}${tail}`;
}
