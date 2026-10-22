import {afterEach, describe, expect, it, vi} from 'vitest';

import {TOKEN_KEY} from '../api/client';
import {downloadMemo, saveBlob} from './download';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('downloadMemo', () => {
  it('fetches the memo with the token and saves it under the server name', async () => {
    window.sessionStorage.setItem(TOKEN_KEY, 'secret-token');
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response('# Memo', {
          headers: {
            'Content-Disposition': 'attachment; filename="keel-memo-req-2.md"',
          },
        }),
      ),
    );
    vi.stubGlobal('fetch', fetchMock);
    const created = vi.fn(() => 'blob:memo');
    const revoked = vi.fn();
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: created,
      revokeObjectURL: revoked,
    });
    const clicks: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push(this);
    });
    const name = await downloadMemo('req-2', 'markdown');
    expect(name).toBe('keel-memo-req-2.md');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/export/req-2?format=markdown',
      {
        headers: {Authorization: 'Bearer secret-token'},
      },
    );
    expect(clicks).toHaveLength(1);
    expect(clicks[0]?.download).toBe('keel-memo-req-2.md');
    expect(clicks[0]?.getAttribute('href')).toBe('blob:memo');
    // The link leaves the document once it was clicked.
    expect(document.querySelector('a[download]')).toBeNull();
  });

  it('builds the DOCX path and falls back to its own name', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response('PK')));
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: () => 'blob:x',
      revokeObjectURL: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const name = await downloadMemo('a/b', 'docx');
    expect(fetchMock).toHaveBeenCalledWith('/api/export/a%2Fb?format=docx', {
      headers: {},
    });
    expect(name).toBe('keel-memo-a/b.docx');
  });

  it('rejects with the API error of a missing answer', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(
            '{"detail":{"code":"not_found","message":"no stored answer"}}',
            {status: 404},
          ),
        ),
      ),
    );
    await expect(downloadMemo('gone', 'markdown')).rejects.toMatchObject({
      status: 404,
      code: 'not_found',
    });
  });
});

describe('saveBlob', () => {
  it('revokes the object URL after a pause', () => {
    vi.useFakeTimers();
    const revoked = vi.fn();
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: () => 'blob:y',
      revokeObjectURL: revoked,
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    saveBlob('a.json', new Blob(['{}']));
    expect(revoked).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(revoked).toHaveBeenCalledWith('blob:y');
    vi.useRealTimers();
  });
});
