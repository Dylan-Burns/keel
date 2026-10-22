/** The 3 example questions (G-06, G-11, G-19 of chapter 18). */

/** An example chip: a short label and the question it sends. */
export interface Example {
  readonly label: string;
  readonly question: string;
}

/** The 3 example chips of the question area, in demo order. */
export const EXAMPLES: readonly Example[] = [
  {
    label: 'Apple, Tesla, JPMorgan risk factors',
    question:
      'What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?',
  },
  {
    label: 'NVIDIA revenue and outlook',
    question:
      "How has NVIDIA's revenue and growth outlook changed over the last two years?",
  },
  {
    label: 'Pharma regulatory risks',
    question:
      'What regulatory risks do the major pharmaceutical companies face, and how are they addressing them?',
  },
];

/** The shortest and the longest question the API accepts (chapter 14.2). */
export const QUESTION_MIN = 3;

/** The longest question the API accepts (chapter 14.2). */
export const QUESTION_MAX = 1000;
