import {fireEvent, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {onOpenApiKeySettings, setApiKey} from '../api/apiKey';
import {ApiKeyPrompt} from './ApiKeyPrompt';

const KEY = 'sk-ant-api03-abcdefghijklmnop_QRST-wxyz';

afterEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
});

describe('ApiKeyPrompt', () => {
  it('asks for a key and opens the settings', () => {
    const listener = vi.fn();
    const stop = onOpenApiKeySettings(listener);
    render(
      <ApiKeyPrompt code="api_key_required" onRetry={vi.fn()} retryEnabled />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Add your Anthropic API key to ask this question.',
    );
    // No key yet: nothing to ask again with.
    expect(screen.queryByRole('button', {name: 'Ask again'})).toBeNull();
    fireEvent.click(screen.getByRole('button', {name: 'Add API key'}));
    expect(listener).toHaveBeenCalledOnce();
    stop();
  });

  it('names a rejected key and asks again once a key is stored', () => {
    setApiKey(KEY, false);
    const onRetry = vi.fn();
    render(
      <ApiKeyPrompt
        code="provider_auth_rejected"
        onRetry={onRetry}
        retryEnabled
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Anthropic rejected the API key.',
    );
    expect(
      screen.getByRole('button', {name: 'Check API key'}),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: 'Ask again'}));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('names a malformed key', () => {
    render(<ApiKeyPrompt code="invalid_api_key" onRetry={null} retryEnabled />);
    expect(screen.getByTestId('api-key-prompt')).toHaveAttribute(
      'data-code',
      'invalid_api_key',
    );
    expect(screen.getByRole('alert')).toHaveTextContent('not an Anthropic key');
  });
});
