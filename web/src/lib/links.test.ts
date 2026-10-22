import {describe, expect, it} from 'vitest';

import {
  rerunPath,
  rerunQuestion,
  sharePath,
  sharedRequestId,
  shareUrl,
} from './links';

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

  it('round-trips a question through the re-run link', () => {
    const question = "How has NVIDIA's revenue changed? (50% & more)";
    const path = rerunPath(question);
    expect(path.startsWith('/?rerun=')).toBe(true);
    expect(rerunQuestion(path.slice(1))).toBe(question);
    expect(rerunQuestion('')).toBeNull();
    expect(rerunQuestion('?rerun=%20')).toBeNull();
  });
});
