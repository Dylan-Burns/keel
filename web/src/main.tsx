import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';

import {App} from './App';
import {CompSetsPage} from './components/CompSetsPage';
import {EvalPage} from './components/EvalPage';
import {HelpPage} from './components/HelpPage';
import {HistoryPage} from './components/HistoryPage';
import {CompaniesPage} from './components/admin/CompaniesPage';
import {DebugPage} from './components/admin/DebugPage';
import {JobsPage} from './components/admin/JobsPage';
import {SystemPage} from './components/admin/SystemPage';
import {UsersPage} from './components/admin/UsersPage';
import {
  COMPANIES_PATH,
  COMPSETS_PATH,
  DEBUG_PATH,
  HELP_PATH,
  HISTORY_PATH,
  JOBS_PATH,
  SYSTEM_PATH,
  USERS_PATH,
  jobIdOf,
} from './lib/links';
import './styles.css';

const container = document.getElementById('root');
if (container === null) {
  throw new Error('the #root element is missing from index.html');
}
// The client routes: `/eval` is the eval page (W-02), `/history` the history
// page and `/compsets` the comp sets page (27.2), `/help` the data use page
// (27.2), `/companies` the watch list and the company jobs, `/jobs` and
// `/jobs/{id}` the admin jobs, `/users` and `/system` the other admin
// pages, `/debug` the debug page; every other path is the question page, which reads the shared
// answer route `/a/{request_id}` itself.
const path = window.location.pathname.replace(/\/+$/, '');
const page =
  path === '/eval' ? (
    <EvalPage />
  ) : path === HISTORY_PATH ? (
    <HistoryPage />
  ) : path === COMPSETS_PATH ? (
    <CompSetsPage />
  ) : path === HELP_PATH ? (
    <HelpPage />
  ) : path === COMPANIES_PATH ? (
    <CompaniesPage />
  ) : path === JOBS_PATH || jobIdOf(path) !== null ? (
    <JobsPage />
  ) : path === USERS_PATH ? (
    <UsersPage />
  ) : path === SYSTEM_PATH ? (
    <SystemPage />
  ) : path === DEBUG_PATH ? (
    <DebugPage />
  ) : (
    <App />
  );
createRoot(container).render(<StrictMode>{page}</StrictMode>);
