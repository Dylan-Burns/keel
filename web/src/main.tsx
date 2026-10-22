import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';

import {App} from './App';
import {CompSetsPage} from './components/CompSetsPage';
import {EvalPage} from './components/EvalPage';
import {HelpPage} from './components/HelpPage';
import {HistoryPage} from './components/HistoryPage';
import {COMPSETS_PATH, HELP_PATH, HISTORY_PATH} from './lib/links';
import './styles.css';

const container = document.getElementById('root');
if (container === null) {
  throw new Error('the #root element is missing from index.html');
}
// The client routes: `/eval` is the eval page (W-02), `/history` the history
// page and `/compsets` the comp sets page (27.2), `/help` the data use page
// (27.2); every other path is the question page, which reads the shared
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
  ) : (
    <App />
  );
createRoot(container).render(<StrictMode>{page}</StrictMode>);
