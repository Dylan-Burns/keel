import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import type {ComparisonTable as Table} from '../api/types';
import {complete, pick} from '../motion/presets';

/** Props of ComparisonTable. */
export interface ComparisonTableProps {
  readonly table: Table;
}

/** A figure: an optional sign or currency, digits, a unit or a percent. */
const NUMERIC =
  /^[(+-]?[$\u20ac\u00a3]?\s?\d[\d,.]*\s?(%|x|bp|bps|[kmb]|bn|mn|million|billion|thousand)?\)?$/i;

/**
 * True when a cell holds a single figure, such as `$94.9B`, `(3.2%)`, or
 * `1,204`: the quote grid right-aligns it in tabular numerals.
 *
 * @param cell The cell text.
 * @return Whether the cell is a number.
 */
export function isNumericCell(cell: string): boolean {
  return NUMERIC.test(cell.trim());
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
    <div className="overflow-x-auto border border-line">
      <table className="grid-table" data-testid="comparison-table">
        <thead>
          <tr>
            {table.columns.map(column => (
              <th key={column} scope="col">
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
                  className={isNumericCell(cell) ? 'cell-num' : undefined}
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
