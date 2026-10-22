import type {JSX} from 'react';

import {scalar} from '../../lib/format';

/** 1 row of a job result table. */
export type Row = Readonly<Record<string, unknown>>;

/** Props of MiniTable. */
export interface MiniTableProps {
  /** The caption above the columns. */
  readonly caption: string;
  /** The keys of the row to show, in order; `_` reads as a space. */
  readonly columns: readonly string[];
  readonly rows: readonly Row[];
  readonly testId: string;
}

/**
 * A small table of chosen columns of a job result, in a box that scrolls
 * sideways on a phone. Every cell is a JSX text node.
 *
 * @param props The props.
 * @return The table.
 */
export function MiniTable({
  caption,
  columns,
  rows,
  testId,
}: MiniTableProps): JSX.Element {
  return (
    <div className="overflow-x-auto border border-line" data-testid={testId}>
      <table className="grid-table">
        <caption className="section-title px-2 py-1.5 text-left">
          {caption}
        </caption>
        <thead>
          <tr>
            {columns.map(column => (
              <th key={column} scope="col">
                {column.replace(/_/g, ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map(column => (
                <td
                  key={column}
                  className="whitespace-nowrap font-mono text-[11.5px]"
                >
                  {scalar(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
