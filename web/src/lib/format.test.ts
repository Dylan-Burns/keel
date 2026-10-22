import {describe, expect, it} from 'vitest';

import {bytes, scalar, usd, when} from './format';

describe('format', () => {
  it('formats sizes, dollars, and missing values', () => {
    expect(bytes(512)).toBe('512 B');
    expect(bytes(123456)).toBe('120.6 KB');
    expect(bytes(3 * 1024 ** 3)).toBe('3.0 GB');
    expect(bytes(null)).toBe('--');
    expect(usd(4.256)).toBe('$4.26');
    expect(usd(0.0936, 4)).toBe('$0.0936');
    expect(usd(undefined)).toBe('--');
    expect(when(null)).toBe('--');
    expect(when('not a date')).toBe('not a date');
  });

  it('turns JSON values into display text', () => {
    expect(scalar(null)).toBe('none');
    expect(scalar(true)).toBe('true');
    expect(scalar(['a', 1])).toBe('a, 1');
    expect(scalar([{a: 1}, {a: 2}])).toBe('2 items');
    expect(scalar({a: 1})).toBe('{"a":1}');
  });
});
