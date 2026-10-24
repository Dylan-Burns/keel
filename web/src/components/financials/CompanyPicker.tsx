import type {JSX} from 'react';

import type {FinancialsCompany} from '../../api/types';

/** Props of CompanyPicker. */
export interface CompanyPickerProps {
  readonly companies: readonly FinancialsCompany[];
  /** The ticker on show, or null before 1 is chosen. */
  readonly ticker: string | null;
  readonly onChange: (ticker: string) => void;
}

/**
 * The company picker of the financials page: the indexed companies by
 * ticker.
 *
 * @param props The props.
 * @return The labelled select.
 */
export function CompanyPicker({
  companies,
  ticker,
  onChange,
}: CompanyPickerProps): JSX.Element {
  return (
    <label className="flex items-center gap-2">
      <span className="section-title">Company</span>
      <select
        className="input num max-w-[16rem] py-1 text-[12px]"
        value={ticker ?? ''}
        data-testid="fin-company"
        onChange={event => onChange(event.target.value)}
      >
        {ticker === null && <option value="">Choose a company</option>}
        {companies.map(company => (
          <option key={company.ticker} value={company.ticker}>
            {`${company.ticker}  ${company.company}`}
          </option>
        ))}
      </select>
    </label>
  );
}
