import {describe, expect, it} from 'vitest';

import {diffPrompt, diffVersions, splitPrompt, wordDiff} from './promptDiff';

const V1 = [
  'You are Keel, an analyst assistant.',
  '',
  'GROUNDING RULES',
  '1. Use only the text inside <context>.',
  '2. Cite every claim',
  '   with a chunk ID.',
  '3. Quote at most 25 words.',
].join('\n');

const V2 = [
  'You are Keel, an analyst assistant.',
  '',
  'GROUNDING RULES',
  '1. Use only the text inside <context>.',
  '2. Cite every factual claim',
  '   with one or more chunk IDs.',
  '',
  'COMPANY FACTS',
  '4. Prefer a fact line for a number.',
].join('\n');

describe('promptDiff', () => {
  it('splits the opening, the headings, and the numbered rules', () => {
    expect(splitPrompt(V1).map(p => [p.key, p.text])).toEqual([
      ['opening', 'You are Keel, an analyst assistant.'],
      ['heading:GROUNDING RULES', 'GROUNDING RULES'],
      ['rule:1', 'Use only the text inside <context>.'],
      ['rule:2', 'Cite every claim with a chunk ID.'],
      ['rule:3', 'Quote at most 25 words.'],
    ]);
  });

  it('lists the changed, new, and removed parts', () => {
    expect(diffPrompt(V1, V2).map(c => [c.kind, c.key, c.label])).toEqual([
      ['changed', 'rule:2', 'Rule 2'],
      ['added', 'heading:COMPANY FACTS', 'Heading COMPANY FACTS'],
      ['added', 'rule:4', 'Rule 4'],
      ['removed', 'rule:3', 'Rule 3'],
    ]);
    expect(diffPrompt(V1, V1)).toEqual([]);
  });

  it('adds the user template as 1 part when it changes', () => {
    const changes = diffVersions(
      {system: V1, user: '<context>\n{context}'},
      {system: V1, user: '{facts}\n<context>\n{context}'},
    );
    expect(changes).toEqual([
      {
        key: 'user',
        label: 'User message template',
        kind: 'changed',
        before: '<context> {context}',
        after: '{facts} <context> {context}',
      },
    ]);
  });

  it('marks the words kept, added, and deleted', () => {
    expect(
      wordDiff('cite every claim', 'cite every factual claim now'),
    ).toEqual([
      {text: 'cite', op: 'same'},
      {text: 'every', op: 'same'},
      {text: 'factual', op: 'add'},
      {text: 'claim', op: 'same'},
      {text: 'now', op: 'add'},
    ]);
    expect(wordDiff('a b', '')).toEqual([
      {text: 'a', op: 'del'},
      {text: 'b', op: 'del'},
    ]);
  });
});
