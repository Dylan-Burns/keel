import type {JSX} from 'react';

import type {ReaderTableData} from '../lib/reader';
import {isCitedRow} from '../lib/reader';

/** Props of ReaderTable. */
export interface ReaderTableProps {
  readonly table: ReaderTableData;
  /** The cited quote: a row whose cells it holds is marked. */
  readonly quote?: string | undefined;
}

/**
 * A table passage of a filing as an HTML table, the cited row marked. Every
 * cell is a JSX text node.
 *
 * @param props The props.
 * @return The table.
 */
export function ReaderTable({table, quote}: ReaderTableProps): JSX.Element {
  const width = Math.max(
    table.columns.length,
    ...table.rows.map(row => row.length),
  );
  const header =
    table.columns.length > 0 && table.columns.length < width
      ? ['', ...table.columns]
      : table.columns;
  return (
    <div className="overflow-x-auto">
      <table className="reader-table" data-testid="reader-table">
        {(table.caption !== '' || table.units !== '') && (
          <caption>
            {table.caption}
            {table.units === '' ? '' : ` (${table.units})`}
          </caption>
        )}
        {header.length > 0 && (
          <thead>
            <tr>
              {header.map((cell, i) => (
                <th key={i} scope="col">
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {table.rows.map((row, r) => {
            const cited = isCitedRow(row, quote);
            return (
              <tr
                key={r}
                data-cited={cited}
                {...(cited ? {'data-reader-target': ''} : {})}
              >
                {row.map((cell, c) => (
                  <td key={c} colSpan={row.length === 1 ? width : undefined}>
                    {cited && cell !== '' ? (
                      <mark className="reader-mark" data-testid="reader-mark">
                        {cell}
                      </mark>
                    ) : (
                      cell
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
