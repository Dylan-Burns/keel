import {describe, expect, it} from 'vitest';

import {sharePath, sharedRequestId, shareUrl} from './links';

describe('links', () => {
  it('builds and reads the shareable link of an answer', () => {
    expect(sharePath('abc-1')).toBe('/a/abc-1');
    expect(shareUrl('abc-1', 'https://keel.example')).toBe(
      'https://keel.example/a/abc-1',
    );
    expect(sharedRequestId('/a/abc-1')).toBe('abc-1');
    expect(sharedRequestId('/a/key.1:x/')).toBe('key.1:x');
    expect(sharedRequestId('/a/')).toBeNull();
    expect(sharedRequestId('/a/x/y')).toBeNull();
    expect(sharedRequestId('/history')).toBeNull();
  });
});
