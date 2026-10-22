import {describe, expect, it} from 'vitest';

import {
  isSecUrl,
  markdownBlocks,
  renderMarkdown,
  sanitizeHtml,
  tagChunkIds,
} from './markdown';

function dom(html: string): HTMLElement {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div;
}

describe('renderMarkdown', () => {
  it('keeps the allowed tags', () => {
    const html = renderMarkdown(
      '**bold** and *em* and `code`\n\n- a\n- b\n\n1. one\n\n| h |\n| - |\n| c |\n',
    );
    const root = dom(html);
    for (const tag of [
      'p',
      'strong',
      'em',
      'code',
      'ul',
      'ol',
      'li',
      'table',
      'thead',
      'tbody',
      'tr',
      'th',
      'td',
    ]) {
      expect(root.querySelector(tag), tag).not.toBeNull();
    }
  });

  it('shows raw HTML of the model as text, never as elements', () => {
    const root = dom(
      renderMarkdown(
        'Hi <script>window.pwned = 1</script><img src=x onerror="alert(1)"><iframe src="x"></iframe>',
      ),
    );
    expect(root.querySelector('script, img, iframe')).toBeNull();
    expect(root.textContent).toContain('<script>window.pwned = 1</script>');
    expect(root.textContent).toContain('<img src=x onerror="alert(1)">');
  });

  it('sanitizes HTML with the allow list (the second layer)', () => {
    const html = sanitizeHtml(
      '<p>ok</p><script>window.pwned = 1</script><img src=x onerror="alert(1)">' +
        '<h1>title</h1><span style="color:red" onclick="x()">s</span>',
    );
    expect(html).not.toMatch(/<script|<img|<h1|<span|onerror|onclick|style=/i);
    expect(html).toContain('<p>ok</p>');
    expect(html).toContain('title');
  });

  it('keeps an https://www.sec.gov link with target and rel', () => {
    const root = dom(
      renderMarkdown('[filing](https://www.sec.gov/Archives/x.htm)'),
    );
    const link = root.querySelector('a');
    expect(link?.getAttribute('href')).toBe(
      'https://www.sec.gov/Archives/x.htm',
    );
    expect(link?.getAttribute('target')).toBe('_blank');
    expect(link?.getAttribute('rel')).toBe('noopener noreferrer');
  });

  it('strips every other link', () => {
    for (const url of [
      'https://evil.example/x',
      'http://www.sec.gov/x',
      'javascript:alert(1)',
      'https://www.sec.gov.evil.example/x',
      'https://user@www.sec.gov/x',
      'https://www.sec.gov:8443/x',
      '/relative',
    ]) {
      const root = dom(renderMarkdown(`[link](${url})`));
      const link = root.querySelector('a');
      expect(link?.hasAttribute('href') ?? false, url).toBe(false);
      expect(root.textContent).toContain('link');
    }
  });

  it('drops attributes outside the allow list', () => {
    const html = sanitizeHtml(
      '<a href="https://www.sec.gov/" title="t" class="c" data-x="1">s</a>',
    );
    expect(html).not.toMatch(/title=|class=|data-x=/);
  });
});

describe('isSecUrl', () => {
  it('accepts https on www.sec.gov only', () => {
    expect(isSecUrl('https://www.sec.gov/cgi-bin/browse-edgar')).toBe(true);
    expect(isSecUrl('https://data.sec.gov/x')).toBe(false);
    expect(isSecUrl('not a url')).toBe(false);
    expect(isSecUrl(null)).toBe(false);
  });
});

describe('markdownBlocks', () => {
  it('splits the top-level blocks and keeps a loose list whole', () => {
    expect(
      markdownBlocks('Intro **bold**\n\n- a\n\n- b\n\n| h |\n| - |\n| c |\n'),
    ).toHaveLength(3);
  });

  it('keeps a growing last block in the same position', () => {
    const before = markdownBlocks('One.\n\nTwo and');
    const after = markdownBlocks('One.\n\nTwo and more text');
    expect(before).toHaveLength(2);
    expect(after).toHaveLength(2);
    expect(after[0]).toBe(before[0]);
  });

  it('returns no block for blank text', () => {
    expect(markdownBlocks('  \n\n ')).toEqual([]);
  });
});

describe('tagChunkIds', () => {
  it('marks an inline chunk ID as code and leaves other brackets', () => {
    expect(
      tagChunkIds('Risk [AAPL_10K_2025-09-27__risk_factors__0002] and [note]'),
    ).toBe('Risk `AAPL_10K_2025-09-27__risk_factors__0002` and [note]');
  });
});
