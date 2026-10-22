import type {JSX} from 'react';

import type {ComparisonTable as Table} from '../api/types';

/** Props of ComparisonTable. */
export interface ComparisonTableProps {
  readonly table: Table;
}

/**
 * The comparison table of a multi-company or multi-period answer. Cells are
 * JSX text nodes.
 *
 * @param props The props.
 * @return The table.
 */
export function ComparisonTable({table}: ComparisonTableProps): JSX.Element {
  return (
    <div className="overflow-x-auto">
      <table
        className="w-full border-collapse text-sm"
        data-testid="comparison-table"
      >
        <thead>
          <tr>
            {table.columns.map(column => (
              <th
                key={column}
                className="border-b border-slate-300 px-2 py-1 text-left font-medium"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  className="border-b border-slate-100 px-2 py-1 align-top"
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
