import type {JSX} from 'react';

import {AdminShell} from './AdminShell';
import {SystemPanels} from './SystemPanels';

/**
 * The system page at `/system` (admins): `keel doctor`, `keel inventory`,
 * the index build, the scheduler, the budget, the backups with download,
 * back up and restore, the index rebuild, the cache warm-up, the eval run,
 * and the admin audit.
 *
 * @return The page.
 */
export function SystemPage(): JSX.Element {
  return (
    <AdminShell title="System" current="system" adminOnly testId="system-page">
      {() => <SystemPanels />}
    </AdminShell>
  );
}
