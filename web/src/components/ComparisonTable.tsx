import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import type {ComparisonTable as Table} from '../api/types';
import {complete, pick} from '../motion/presets';

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
  const reduced = useReducedMotion();
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
        <motion.tbody
          variants={pick(complete.rows, reduced)}
          initial="hidden"
          animate="visible"
        >
          {table.rows.map((row, rowIndex) => (
            <motion.tr key={rowIndex} variants={pick(complete.row, reduced)}>
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  className="border-b border-slate-100 px-2 py-1 align-top"
                >
                  {cell}
                </td>
              ))}
            </motion.tr>
          ))}
        </motion.tbody>
      </table>
    </div>
  );
}
