/**
 * Motion presets for every animated moment of chapter 14.8. Components import
 * these and never define an inline transition. There is 1 named export per
 * moment of the table; each part of a moment has a `reduced` twin that shows
 * the final state at once, including the trace drawer (W-01) and the eval
 * page (W-02).
 *
 * Rules (14.8): every animation takes 300 ms or less, except the count up
 * (600 ms) and the chunk stagger (30 ms per chunk, 48 chunks at most). An
 * animation never changes what the data says, and the text is in the DOM
 * before it moves.
 */
import type {Transition, Variants} from 'motion/react';

/** A variants pair: the full animation and its reduced-motion twin. */
export interface MotionPreset {
  readonly full: Variants;
  readonly reduced: Variants;
}

/** A transition pair, for a motion value or a layout animation. */
export interface TransitionPreset {
  readonly full: Transition;
  readonly reduced: Transition;
}

/** The reduced twin of a fade or slide: the visible state, no time. */
const STILL: Variants = {
  hidden: {opacity: 1, x: 0, y: 0, scale: 1},
  visible: {opacity: 1, x: 0, y: 0, scale: 1, transition: {duration: 0}},
};

/** A container whose only job is to stagger its children. */
function stagger(seconds: number): MotionPreset {
  return {
    full: {
      hidden: {},
      visible: {transition: {staggerChildren: seconds}},
    },
    reduced: {hidden: {}, visible: {transition: {staggerChildren: 0}}},
  };
}

/**
 * Page load: the top bar and the question area fade in, and the 3 example
 * chips stagger in 60 ms apart. Once per load.
 */
export const pageLoad = {
  region: {
    full: {
      hidden: {opacity: 0, y: 8},
      visible: {opacity: 1, y: 0, transition: {duration: 0.3, ease: 'easeOut'}},
    },
    reduced: STILL,
  },
  chips: stagger(0.06),
  chip: {
    full: {
      hidden: {opacity: 0, y: 6},
      visible: {opacity: 1, y: 0, transition: {duration: 0.2, ease: 'easeOut'}},
    },
    reduced: STILL,
  },
} as const satisfies Record<string, MotionPreset>;

/**
 * Question sent: the 3 progress steps light up in sequence as the `meta`,
 * `analysis`, and `retrieval` events arrive; the active step pulses until the
 * first `answer_delta`.
 */
export const questionSent = {
  step: {
    full: {
      off: {opacity: 0.6, scale: 1},
      lit: {opacity: 1, scale: 1, transition: {duration: 0.2}},
      pulse: {
        opacity: [1, 0.55, 1],
        transition: {duration: 0.3, repeat: Infinity, repeatDelay: 0.3},
      },
    },
    reduced: {
      off: {opacity: 0.6, scale: 1},
      lit: {opacity: 1, scale: 1, transition: {duration: 0}},
      pulse: {opacity: 1, scale: 1, transition: {duration: 0}},
    },
  },
} as const satisfies Record<string, MotionPreset>;

/** Entities resolved: the entity chips spring in from the left. */
export const entitiesResolved = {
  chips: stagger(0.04),
  chip: {
    full: {
      hidden: {opacity: 0, x: -16},
      visible: {
        opacity: 1,
        x: 0,
        transition: {type: 'spring', stiffness: 300, damping: 25},
      },
    },
    reduced: STILL,
  },
} as const satisfies Record<string, MotionPreset>;

/**
 * Retrieval: the chunks stagger in from the bottom 30 ms apart, each in 80 ms,
 * so 48 chunks end under 1.5 s (47 x 30 + 80 = 1490 ms), and the score bars grow to their width.
 */
export const retrieval = {
  list: stagger(0.03),
  item: {
    full: {
      hidden: {opacity: 0, y: 10},
      visible: {
        opacity: 1,
        y: 0,
        transition: {duration: 0.08, ease: 'easeOut'},
      },
    },
    reduced: STILL,
  },
  bar: {
    full: {
      hidden: {scaleX: 0},
      visible: {scaleX: 1, transition: {duration: 0.08, ease: 'easeOut'}},
    },
    reduced: {
      hidden: {scaleX: 1},
      visible: {scaleX: 1, transition: {duration: 0}},
    },
  },
} as const satisfies Record<string, MotionPreset>;

/**
 * Stream: the answer grows 1 markdown block (a paragraph, a list, a table) at
 * a time. Each block fades in once, in 160 ms with no offset, when it first
 * appears; later deltas grow the last block in place with no new fade, so
 * nothing flickers or jumps. The text is in the DOM before the fade starts,
 * and the cursor blinks.
 */
export const stream = {
  section: {
    full: {
      hidden: {opacity: 0},
      visible: {opacity: 1, transition: {duration: 0.16, ease: 'easeOut'}},
    },
    reduced: STILL,
  },
  cursor: {
    full: {
      hidden: {opacity: 1},
      visible: {
        opacity: [1, 0],
        transition: {
          duration: 0.3,
          repeat: Infinity,
          repeatType: 'reverse',
          repeatDelay: 0.25,
        },
      },
    },
    reduced: {
      hidden: {opacity: 1},
      visible: {opacity: 1, transition: {duration: 0}},
    },
  },
} as const satisfies Record<string, MotionPreset>;

/**
 * Complete: the findings groups expand with a height animation, the citation
 * chips pop in with a stagger, and the comparison table rows stagger in.
 */
export const complete = {
  findings: {
    full: {
      hidden: {height: 0, opacity: 0},
      visible: {
        height: 'auto',
        opacity: 1,
        transition: {duration: 0.3, ease: 'easeOut'},
      },
    },
    reduced: {
      hidden: {height: 'auto', opacity: 1},
      visible: {height: 'auto', opacity: 1, transition: {duration: 0}},
    },
  },
  chips: stagger(0.04),
  chip: {
    full: {
      hidden: {opacity: 0, scale: 0.8},
      visible: {
        opacity: 1,
        scale: 1,
        transition: {duration: 0.15, ease: 'easeOut'},
      },
    },
    reduced: STILL,
  },
  rows: stagger(0.05),
  row: {
    full: {
      hidden: {opacity: 0, y: 4},
      visible: {opacity: 1, y: 0, transition: {duration: 0.2}},
    },
    reduced: STILL,
  },
} as const satisfies Record<string, MotionPreset>;

/**
 * Complete, the badge: the latency and cost badge counts up from 0 to the
 * measured value over 600 ms (`animate` on a motion value).
 */
export const countUp: TransitionPreset = {
  full: {duration: 0.6, ease: 'easeOut'},
  reduced: {duration: 0},
};

/**
 * Partial coverage, provider down, stale index, offline: the banner slides
 * down from the top bar. A banner never leaves the screen on its own.
 */
export const banner = {
  slide: {
    full: {
      hidden: {opacity: 0, y: -12},
      visible: {
        opacity: 1,
        y: 0,
        transition: {duration: 0.25, ease: 'easeOut'},
      },
    },
    reduced: STILL,
  },
} as const satisfies Record<string, MotionPreset>;

/**
 * Deliberate failure (W-04): the gray out-of-scope card fades in with the
 * example chips, with the durations of the normal path.
 */
export const outOfScope = {
  card: {
    full: {
      hidden: {opacity: 0},
      visible: {opacity: 1, transition: {duration: 0.3}},
    },
    reduced: STILL,
  },
} as const satisfies Record<string, MotionPreset>;

/**
 * Trace drawer (W-01): the drawer slides up with a spring inside
 * `AnimatePresence`, and the line `model requests: 1` draws attention with 1
 * scale pulse, once per answer (the line is in the DOM before it pulses).
 */
export const traceDrawer = {
  drawer: {
    full: {
      hidden: {opacity: 0, y: 24},
      visible: {
        opacity: 1,
        y: 0,
        transition: {type: 'spring', visualDuration: 0.3, bounce: 0.2},
      },
      exit: {opacity: 0, y: 24, transition: {duration: 0.2}},
    },
    reduced: {
      hidden: {opacity: 1, y: 0},
      visible: {opacity: 1, y: 0, transition: {duration: 0}},
      exit: {opacity: 1, y: 0, transition: {duration: 0}},
    },
  },
  pulse: {
    full: {
      hidden: {scale: 1},
      visible: {
        scale: [1, 1.12, 1],
        transition: {duration: 0.2, delay: 0.1, ease: 'easeOut'},
      },
    },
    reduced: {
      hidden: {scale: 1},
      visible: {scale: 1, transition: {duration: 0}},
    },
  },
} as const satisfies Record<string, MotionPreset>;

/**
 * Filing reader: the panel slides in from the right over a fading backdrop
 * when a citation opens it; the reduced twin shows it at once.
 */
export const filingReader = {
  backdrop: {
    full: {
      hidden: {opacity: 0},
      visible: {opacity: 1, transition: {duration: 0.2}},
      exit: {opacity: 0, transition: {duration: 0.15}},
    },
    reduced: {
      hidden: {opacity: 1},
      visible: {opacity: 1, transition: {duration: 0}},
      exit: {opacity: 1, transition: {duration: 0}},
    },
  },
  panel: {
    full: {
      hidden: {opacity: 0, x: 32},
      visible: {
        opacity: 1,
        x: 0,
        transition: {duration: 0.25, ease: 'easeOut'},
      },
      exit: {opacity: 0, x: 32, transition: {duration: 0.15}},
    },
    reduced: {
      hidden: {opacity: 1, x: 0},
      visible: {opacity: 1, x: 0, transition: {duration: 0}},
      exit: {opacity: 1, x: 0, transition: {duration: 0}},
    },
  },
} as const satisfies Record<string, MotionPreset>;

/**
 * Eval page (W-02): the metric bars grow to their values on first view; the
 * number is in the DOM before the bar moves, and a value below its gate turns
 * red at the end of the grow.
 */
export const evalPage = {
  bars: stagger(0.05),
  bar: {
    full: {
      hidden: {scaleX: 0},
      visible: {scaleX: 1, transition: {duration: 0.3, ease: 'easeOut'}},
    },
    reduced: {
      hidden: {scaleX: 1},
      visible: {scaleX: 1, transition: {duration: 0}},
    },
  },
} as const satisfies Record<string, MotionPreset>;

/**
 * Job steps (the admin job view): the running step's ring turns (8 dashes,
 * 45 degrees per 300 ms, so the loop has no seam), a finished step's icon
 * pops in, a step log opens with a height animation, and the progress bars
 * grow to their value. The reduced twins hold still: the ring stays put, the
 * icon and the log show at once, and the bars jump to their value.
 */
export const jobSteps = {
  spinner: {
    full: {
      idle: {rotate: 0},
      spin: {
        rotate: [0, 45],
        transition: {duration: 0.3, ease: 'linear', repeat: Infinity},
      },
    },
    reduced: {
      idle: {rotate: 0},
      spin: {rotate: 0, transition: {duration: 0}},
    },
  },
  icon: {
    full: {
      hidden: {opacity: 0, scale: 0.6},
      visible: {
        opacity: 1,
        scale: 1,
        transition: {duration: 0.2, ease: 'easeOut'},
      },
    },
    reduced: STILL,
  },
  log: {
    full: {
      hidden: {height: 0, opacity: 0},
      visible: {
        height: 'auto',
        opacity: 1,
        transition: {duration: 0.2, ease: 'easeOut'},
      },
      exit: {height: 0, opacity: 0, transition: {duration: 0.15}},
    },
    reduced: {
      hidden: {height: 'auto', opacity: 1},
      visible: {height: 'auto', opacity: 1, transition: {duration: 0}},
      exit: {height: 'auto', opacity: 1, transition: {duration: 0}},
    },
  },
} as const satisfies Record<string, MotionPreset>;

/** Job steps: a progress bar grows to its new value (a transition pair). */
export const jobBar: TransitionPreset = {
  full: {duration: 0.3, ease: 'easeOut'},
  reduced: {duration: 0},
};

/**
 * State change: a `layout="position"` animation on the answer container keeps
 * the question area in place when the answer area changes height. Position
 * only: a size layout animation scales the container, which squashed the
 * streaming text on every new block.
 */
export const stateChange: TransitionPreset = {
  full: {layout: {duration: 0.3, ease: 'easeOut'}},
  reduced: {layout: {duration: 0}},
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

/**
 * Picks the full or the reduced transition of a preset.
 *
 * @param preset The transition pair.
 * @param reducedMotion The value of `useReducedMotion()`.
 * @return The transition.
 */
export function pickTransition(
  preset: TransitionPreset,
  reducedMotion: boolean | null,
): Transition {
  return reducedMotion === true ? preset.reduced : preset.full;
}
