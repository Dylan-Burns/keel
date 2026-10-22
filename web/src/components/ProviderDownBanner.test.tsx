import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';

import {ProviderDownBanner} from './ProviderDownBanner';

describe('ProviderDownBanner', () => {
  it('says the model is unavailable and retries', () => {
    const onRetry = vi.fn();
    render(
      <ProviderDownBanner
        message="No answer."
        onRetry={onRetry}
        retryEnabled
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Model unavailable. No answer.',
    );
    fireEvent.click(screen.getByRole('button', {name: 'Retry'}));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('has no Retry before any question', () => {
    render(
      <ProviderDownBanner message="No key." onRetry={null} retryEnabled />,
    );
    expect(screen.queryByRole('button')).toBeNull();
  });
});
