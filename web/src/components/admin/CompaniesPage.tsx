import type {JSX} from 'react';
import {useCallback, useState} from 'react';

import {AddCompany} from './AddCompany';
import {AdminShell} from './AdminShell';
import {CompanyBrowser} from './CompanyBrowser';
import {FactsPanel} from './FactsPanel';
import {RefreshPanel} from './RefreshPanel';
import {WatchPanel} from './WatchPanel';

/**
 * The companies page at `/companies`: the watch list for every user, and
 * for an admin the add-a-company job (`keel add`), the company browser by
 * SEC industry with an Add button per company, watch list changes
 * (`keel watch`), the refresh with its dry run (`keel refresh`), and the
 * company facts (`keel facts`).
 *
 * @return The page.
 */
export function CompaniesPage(): JSX.Element {
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion(n => n + 1), []);
  return (
    <AdminShell
      title="Companies"
      current="companies"
      adminOnly={false}
      testId="companies-page"
    >
      {isAdmin => (
        <>
          {isAdmin && (
            <div className="grid items-start gap-3 lg:grid-cols-2">
              <AddCompany onDone={reload} />
              <RefreshPanel onDone={reload} />
            </div>
          )}
          {isAdmin && <CompanyBrowser onDone={reload} />}
          <WatchPanel isAdmin={isAdmin} version={version} />
          {isAdmin && <FactsPanel />}
        </>
      )}
    </AdminShell>
  );
}
