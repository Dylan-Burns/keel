import {fireEvent, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import type {TemplateList} from '../api/types';
import {TemplatePicker} from './TemplatePicker';

const TEMPLATES: TemplateList = {
  items: [
    {
      id: 'public_comparables',
      label: 'Public comparables',
      text: 'Compare {companies} for {period}.',
      default_period: 'the latest fiscal year',
    },
    {
      id: 'regulatory_scan',
      label: 'Regulatory scan',
      text: 'What regulatory risks do {companies} report for {period}?',
      default_period: 'the latest fiscal year',
    },
  ],
};

function serve(status = 200): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(() =>
    Promise.resolve(
      status === 200
        ? new Response(JSON.stringify(TEMPLATES))
        : new Response('{}', {status}),
    ),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('TemplatePicker', () => {
  it('fills a template into the question box and sends nothing', async () => {
    const fetchMock = serve();
    const onFill = vi.fn();
    render(<TemplatePicker enabled onFill={onFill} />);
    const buttons = await screen.findAllByTestId('template-button');
    expect(buttons.map(b => b.textContent)).toEqual([
      'Public comparables',
      'Regulatory scan',
    ]);
    fireEvent.click(buttons[1] as HTMLElement);
    expect(screen.getByTestId('template-fill')).toBeDisabled();
    fireEvent.change(screen.getByTestId('template-companies'), {
      target: {value: 'my pharma comps'},
    });
    fireEvent.click(screen.getByTestId('template-fill'));
    expect(onFill).toHaveBeenCalledWith(
      'What regulatory risks do my pharma comps report for the latest fiscal year?',
    );
    // Only the templates were fetched: Fill asks nothing.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('template-form')).toBeNull();
  });

  it('uses the period field when given', async () => {
    serve();
    const onFill = vi.fn();
    render(<TemplatePicker enabled onFill={onFill} />);
    fireEvent.click((await screen.findAllByTestId('template-button'))[0]!);
    fireEvent.change(screen.getByTestId('template-companies'), {
      target: {value: 'Apple, Tesla'},
    });
    fireEvent.change(screen.getByTestId('template-period'), {
      target: {value: 'fiscal 2024'},
    });
    fireEvent.submit(screen.getByTestId('template-form'));
    expect(onFill).toHaveBeenCalledWith(
      'Compare Apple, Tesla for fiscal 2024.',
    );
  });

  it('shows nothing without a token or when the templates fail', async () => {
    const fetchMock = serve(503);
    const {container, rerender} = render(
      <TemplatePicker enabled={false} onFill={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(fetchMock).not.toHaveBeenCalled();
    rerender(<TemplatePicker enabled onFill={vi.fn()} />);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(container).toBeEmptyDOMElement();
  });
});
