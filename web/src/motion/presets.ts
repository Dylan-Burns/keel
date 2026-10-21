/**
 * Motion presets for every animated moment of chapter 14.8. Components import
 * these and never define an inline transition. Each preset has a `reduced`
 * twin that shows the final state at once.
 */
import type {Variants} from 'motion/react';

/** A preset pair: the full animation and its reduced-motion twin. */
export interface MotionPreset {
  readonly full: Variants;
  readonly reduced: Variants;
}

/** Page load: the top bar and the question area fade in. */
export const pageLoad: MotionPreset = {
  full: {
    hidden: {opacity: 0, y: 8},
    visible: {opacity: 1, y: 0, transition: {duration: 0.3, ease: 'easeOut'}},
  },
  reduced: {
    hidden: {opacity: 1, y: 0},
    visible: {opacity: 1, y: 0, transition: {duration: 0}},
  },
};

/**
 * Picks the full or the reduced variants of a preset.
 *
 * @param preset The preset pair.
 * @param reducedMotion The value of `useReducedMotion()`; only `true` counts
 *     as reduced, because the hook returns `null` before hydration.
 * @return The variants to pass to a motion component.
 */
export function pick(
  preset: MotionPreset,
  reducedMotion: boolean | null,
): Variants {
  return reducedMotion === true ? preset.reduced : preset.full;
}
