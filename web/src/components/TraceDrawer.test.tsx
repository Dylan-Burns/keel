import {fireEvent, render, screen, within} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import type {AuditRecord} from '../api/types';
import {RESPONSE_1} from '../testing/fixtures';
import {TraceDrawer, requestLine, traceLines} from './TraceDrawer';

const AUDIT = RESPONSE_1.audit as AuditRecord;

describe('TraceDrawer', () => {
  it('shows the audit record in pipeline order with model requests: 1', () => {
    render(<TraceDrawer audit={AUDIT} />);
    const body = screen.getByTestId('trace-body');
    expect(screen.getByTestId('model-requests')).toHaveTextContent(
      'model requests: 1',
    );
    const text = body.textContent ?? '';
    const order = [
      'AAPL, TSLA, JPM',
      'comparison, time scope none',
      'filter JPM risk',
      'JPM 2025-01-01 to 2025-12-31',
      '18 gathered, 16 reranked, 2 near-duplicates collapsed',
      '10 before collapse, 9 after',
      'quota JPM',
      '11 of 16',
      '2 chunks, 2,400 estimated tokens',
      'sha256:0000',
      'model requests: 1',
      '2,400 input, 0 cached, 320 output',
      '$0.0120',
      'first token 0.5 s, total 1.8 s',
      '0 dropped',
    ];
    let at = -1;
    for (const part of order) {
      const found = text.indexOf(part, at + 1);
      expect(found, part).toBeGreaterThan(at);
      at = found;
    }
    expect(text).not.toContain('from_cache');
    expect(text).not.toContain('facts');
  });

  it('words a retry before content and shows the flags and the facts', () => {
    const audit: AuditRecord = {
      ...AUDIT,
      model_requests: 2,
      failed_before_content: 1,
      citation_drift: 1,
      flags: {from_cache: true, degraded: true},
      facts_lines: 4,
      facts_source: 'cache',
      fact_ids: ['f1', 'f2'],
    };
    expect(requestLine(audit)).toBe(
      'model requests: 2 (1 failed before content)',
    );
    render(<TraceDrawer audit={audit} />);
    const body = screen.getByTestId('trace-body');
    expect(within(body).getByTestId('model-requests')).toHaveTextContent(
      'model requests: 2 (1 failed before content)',
    );
    expect(body).toHaveTextContent('from_cache, degraded');
    expect(body).toHaveTextContent('1 dropped');
    expect(body).toHaveTextContent('4 lines from cache, 2 fact IDs');
  });

  it('renders a minimal record and hides and shows its body', () => {
    render(<TraceDrawer audit={{model_requests: 0}} />);
    expect(screen.getByTestId('model-requests')).toHaveTextContent(
      'model requests: 0',
    );
    expect(screen.getByTestId('trace-body')).toHaveTextContent('entitiesnone');
    const toggle = screen.getByTestId('trace-toggle');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('trace-body')).toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByTestId('model-requests')).toBeInTheDocument();
  });

  it('renders model-controlled labels as text, never as HTML', () => {
    const lines = traceLines({
      ...AUDIT,
      error: '<img src=x onerror=alert(1)>',
    });
    expect(lines.after.at(-1)?.value).toBe('<img src=x onerror=alert(1)>');
    render(
      <TraceDrawer audit={{...AUDIT, error: '<img src=x onerror=alert(1)>'}} />,
    );
    expect(document.querySelector('[data-testid="trace-body"] img')).toBeNull();
  });
});
