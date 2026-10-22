import type {JSX} from 'react';

import type {DoctorCheck} from '../../api/types';
import {OpsPanelHead} from './OpsPanelHead';

/** Props of DoctorPanel. */
export interface DoctorPanelProps {
  readonly checks: readonly DoctorCheck[];
  /** True when a check failed. */
  readonly failed: boolean;
}

const TAG: Readonly<Record<DoctorCheck['status'], string>> = {
  ok: 'tag-up',
  warn: 'tag-warn',
  fail: 'tag-down',
};

/**
 * The checks of `keel doctor` (without the model download): 1 row each
 * with its status tag and detail.
 *
 * @param props The props.
 * @return The panel.
 */
export function DoctorPanel({checks, failed}: DoctorPanelProps): JSX.Element {
  return (
    <section className="panel" aria-label="Doctor" data-testid="sys-doctor">
      <OpsPanelHead title="Doctor" note="keel doctor">
        <span className={`tag ${failed ? 'tag-down' : 'tag-up'}`}>
          {failed ? 'a check failed' : 'all checks pass'}
        </span>
      </OpsPanelHead>
      <div className="overflow-x-auto">
        <table className="grid-table">
          <thead>
            <tr>
              <th scope="col">Check</th>
              <th scope="col">Status</th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>
            {checks.map(check => (
              <tr key={check.name} data-testid="doctor-row">
                <td className="whitespace-nowrap font-mono text-[11.5px]">
                  {check.name}
                </td>
                <td>
                  <span className={`tag ${TAG[check.status]}`}>
                    {check.status}
                  </span>
                </td>
                <td className="min-w-[16rem] text-[12px] text-ink-2 [overflow-wrap:anywhere]">
                  {check.detail}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
