import type {JSX} from 'react';

import {AdminShell} from './AdminShell';
import {DebugPanels} from './DebugPanels';

/**
 * The debug page at `/debug` (every role): `keel understand` and
 * `keel retrieve --summary` for a question, with 0 model requests.
 *
 * @return The page.
 */
export function DebugPage(): JSX.Element {
  return (
    <AdminShell
      title="Debug"
      current="debug"
      adminOnly={false}
      testId="debug-page"
    >
      {() => <DebugPanels />}
    </AdminShell>
  );
}
