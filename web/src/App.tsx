import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';

import {pageLoad, pick} from './motion/presets';

/**
 * The stage 0 placeholder page: the product name with one fade in. Stage 9
 * replaces it with the regions of chapter 14.5.
 *
 * @return The page.
 */
export function App(): JSX.Element {
  const reducedMotion = useReducedMotion();
  return (
    <main className="flex min-h-screen items-center justify-center bg-paper text-ink font-sans">
      <motion.h1
        className="text-5xl font-semibold tracking-tight text-accent"
        variants={pick(pageLoad, reducedMotion)}
        initial="hidden"
        animate="visible"
      >
        Keel
      </motion.h1>
    </main>
  );
}
