import type {JSX} from 'react';

import type {DirectorySector} from '../../api/types';
import {BROWSER_COLUMNS} from './CompanyRow';
import type {IndustryLoad} from './IndustryRows';
import {IndustryRows} from './IndustryRows';
import {TreeToggle} from './TreeToggle';
import type {CompanyAdder} from './useCompanyAdder';

/** Props of SectorRows. */
export interface SectorRowsProps {
  readonly sector: DirectorySector;
  readonly open: boolean;
  /** The SIC codes of the open industries. */
  readonly openIndustries: ReadonlySet<string>;
  /** The company lists asked for, by SIC code. */
  readonly loads: Readonly<Record<string, IndustryLoad>>;
  readonly adder: CompanyAdder;
  readonly onToggle: (name: string) => void;
  readonly onToggleIndustry: (code: string) => void;
  readonly onRetry: (code: string) => void;
}

/**
 * 1 sector (an SEC office) and, when open, its industries.
 *
 * @param props The sector, the open rows, the loads, and the actions.
 * @return The rows.
 */
export function SectorRows({
  sector,
  open,
  openIndustries,
  loads,
  adder,
  onToggle,
  onToggleIndustry,
  onRetry,
}: SectorRowsProps): JSX.Element {
  const count = sector.industries.length;
  return (
    <>
      <tr
        className="bg-head"
        data-testid="sector-row"
        data-sector={sector.name}
      >
        <td colSpan={BROWSER_COLUMNS}>
          <TreeToggle
            open={open}
            testId="sector-toggle"
            onToggle={() => onToggle(sector.name)}
          >
            <span className="min-w-0 flex-1 break-words">{sector.name}</span>
            <span className="shrink-0 font-mono text-[10.5px] font-normal text-muted">
              {count === 1 ? '1 industry' : `${count} industries`}
            </span>
          </TreeToggle>
        </td>
      </tr>
      {open &&
        sector.industries.map(industry => (
          <IndustryRows
            key={industry.code}
            industry={industry}
            open={openIndustries.has(industry.code)}
            load={loads[industry.code]}
            adder={adder}
            onToggle={onToggleIndustry}
            onRetry={onRetry}
          />
        ))}
    </>
  );
}
