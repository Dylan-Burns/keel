import {afterEach, describe, expect, it, vi} from 'vitest';

import {copyText, sharePath, sharedRequestId, shareUrl} from './links';

afterEach(() => vi.unstubAllGlobals());

describe('links', () => {
  it('builds and reads the shareable link of an answer', () => {
    expect(sharePath('abc-1')).toBe('/a/abc-1');
    expect(shareUrl('abc-1', 'https://keel.example')).toBe(
      'https://keel.example/a/abc-1',
    );
    expect(sharedRequestId('/a/abc-1')).toBe('abc-1');
    expect(sharedRequestId('/a/key.1:x/')).toBe('key.1:x');
    expect(sharedRequestId(sharePath('key.1:x'))).toBe('key.1:x');
    expect(sharedRequestId('/a/')).toBeNull();
    expect(sharedRequestId('/a/x/y')).toBeNull();
    expect(sharedRequestId('/history')).toBeNull();
  });

  it('rejects a copy without a clipboard instead of throwing', async () => {
    vi.stubGlobal('navigator', {onLine: true});
    await expect(copyText('x')).rejects.toThrow('no clipboard');
  });
});
