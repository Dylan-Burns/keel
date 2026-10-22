import type {Variants} from 'motion/react';
import {describe, expect, it} from 'vitest';

import type {MotionPreset} from './presets';
import * as presets from './presets';
import {
  countUp,
  pageLoad,
  pick,
  pickTransition,
  retrieval,
  stateChange,
} from './presets';

const MOMENTS = [
  'pageLoad',
  'questionSent',
  'entitiesResolved',
  'retrieval',
  'stream',
  'complete',
  'banner',
  'outOfScope',
] as const;

function variantPairs(): [string, MotionPreset][] {
  const pairs: [string, MotionPreset][] = [];
  for (const moment of MOMENTS) {
    const parts = presets[moment] as Record<string, MotionPreset>;
    for (const [part, preset] of Object.entries(parts)) {
      pairs.push([`${moment}.${part}`, preset]);
    }
  }
  return pairs;
}

function durations(variants: Variants): number[] {
  const found: number[] = [];
  for (const target of Object.values(variants)) {
    if (typeof target !== 'object' || target === null) {
      continue;
    }
    const transition = (target as {transition?: {duration?: number}})
      .transition;
    if (transition?.duration !== undefined) {
      found.push(transition.duration);
    }
  }
  return found;
}

describe('motion presets (chapter 14.8)', () => {
  it('has 1 export per moment of the table, each with a reduced twin', () => {
    for (const [name, preset] of variantPairs()) {
      expect(preset.full, name).toBeDefined();
      expect(preset.reduced, name).toBeDefined();
    }
    expect(countUp.reduced).toEqual({duration: 0});
    expect(stateChange.reduced).toEqual({layout: {duration: 0}});
  });

  it('keeps every full animation at 300 ms or less, except the count up', () => {
    for (const [name, preset] of variantPairs()) {
      for (const duration of durations(preset.full)) {
        expect(duration, name).toBeLessThanOrEqual(0.3);
      }
    }
    expect(countUp.full).toMatchObject({duration: 0.6});
  });

  it('ends the chunk stagger of 48 chunks under 1.5 s', () => {
    const visible = retrieval.list.full['visible'] as {
      transition: {staggerChildren: number};
    };
    const last = Math.max(
      ...durations(retrieval.item.full),
      ...durations(retrieval.bar.full),
    );
    expect(47 * visible.transition.staggerChildren + last).toBeLessThan(1.5);
  });

  it('makes every reduced twin a still frame with no time', () => {
    for (const [name, preset] of variantPairs()) {
      for (const duration of durations(preset.reduced)) {
        expect(duration, name).toBe(0);
      }
      for (const target of Object.values(preset.reduced)) {
        const t = target as Record<string, unknown>;
        for (const value of Object.values(t)) {
          expect(Array.isArray(value), `${name} has a keyframe loop`).toBe(
            false,
          );
        }
      }
    }
  });

  it('uses the reduced twin only when reduced motion is true', () => {
    expect(pick(pageLoad.region, true)).toBe(pageLoad.region.reduced);
    expect(pick(pageLoad.region, false)).toBe(pageLoad.region.full);
    expect(pick(pageLoad.region, null)).toBe(pageLoad.region.full);
    expect(pickTransition(countUp, true)).toBe(countUp.reduced);
    expect(pickTransition(countUp, null)).toBe(countUp.full);
  });
});
