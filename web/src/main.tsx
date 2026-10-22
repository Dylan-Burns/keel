import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';

import {App} from './App';
import {EvalPage} from './components/EvalPage';
import './styles.css';

const container = document.getElementById('root');
if (container === null) {
  throw new Error('the #root element is missing from index.html');
}
// The client routes: `/eval` is the eval page (W-02); every other path is the
// question page, which reads `/a/{request_id}` itself.
const isEval = window.location.pathname.replace(/\/+$/, '') === '/eval';
createRoot(container).render(
  <StrictMode>{isEval ? <EvalPage /> : <App />}</StrictMode>,
);
