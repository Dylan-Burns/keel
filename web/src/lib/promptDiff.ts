/**
 * Compares 2 versions of the answer prompt rule by rule. The system block
 * is an opening paragraph, then headings in capitals (GROUNDING RULES),
 * each followed by numbered rules; a rule runs on over indented lines.
 * Pure functions; no request.
 */

/** 1 part of a prompt: the opening, a heading, a rule, or the user block. */
export interface PromptPart {
  /** A stable key across versions, such as `rule:7`. */
  readonly key: string;
  /** The reader's name for it, such as "Rule 7". */
  readonly label: string;
  /** The text with its line breaks joined into 1 line. */
  readonly text: string;
}

/** 1 part that differs between 2 versions. */
export interface PartChange {
  readonly key: string;
  readonly label: string;
  readonly kind: 'changed' | 'added' | 'removed';
  readonly before: string | null;
  readonly after: string | null;
}

/** 1 word of a word diff. */
export interface DiffToken {
  readonly text: string;
  readonly op: 'same' | 'add' | 'del';
}

const RULE = /^(\d+)\.\s+(.*)$/;
const HEADING = /^[A-Z][A-Z ]+[A-Z]$/;

const oneLine = (lines: readonly string[]): string =>
  lines.join(' ').replace(/\s+/g, ' ').trim();

/**
 * Splits a system block into its opening, headings, and numbered rules.
 *
 * @param text The system block.
 * @return The parts in order.
 */
export function splitPrompt(text: string): PromptPart[] {
  const parts: PromptPart[] = [];
  let key = 'opening';
  let label = 'Opening';
  let lines: string[] = [];
  const flush = (): void => {
    const joined = oneLine(lines);
    if (joined !== '') {
      parts.push({key, label, text: joined});
    }
    lines = [];
  };
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    const rule = RULE.exec(line);
    if (rule !== null) {
      flush();
      key = `rule:${rule[1] ?? ''}`;
      label = `Rule ${rule[1] ?? ''}`;
      lines = [rule[2] ?? ''];
    } else if (HEADING.test(line)) {
      flush();
      parts.push({
        key: `heading:${line}`,
        label: `Heading ${line}`,
        text: line,
      });
      key = `after:${line}`;
      label = `Text under ${line}`;
    } else if (line !== '') {
      lines.push(line);
    }
  }
  flush();
  return parts;
}

/**
 * The parts that differ between 2 versions, in the order of the newer
 * version, then the removed parts.
 *
 * @param before The older system block.
 * @param after The newer system block.
 * @return The changes; empty when the 2 match.
 */
export function diffPrompt(before: string, after: string): PartChange[] {
  const old = new Map(splitPrompt(before).map(p => [p.key, p]));
  const changes: PartChange[] = [];
  const seen = new Set<string>();
  for (const part of splitPrompt(after)) {
    seen.add(part.key);
    const was = old.get(part.key);
    if (was === undefined) {
      changes.push({...part, kind: 'added', before: null, after: part.text});
    } else if (was.text !== part.text) {
      changes.push({
        key: part.key,
        label: part.label,
        kind: 'changed',
        before: was.text,
        after: part.text,
      });
    }
  }
  for (const [key, part] of old) {
    if (!seen.has(key)) {
      changes.push({...part, kind: 'removed', before: part.text, after: null});
    }
  }
  return changes;
}

/**
 * A word diff of 2 texts by their longest common run of words.
 *
 * @param before The older text.
 * @param after The newer text.
 * @return The words in order, each kept, added, or deleted.
 */
export function wordDiff(before: string, after: string): DiffToken[] {
  const a = before.split(/\s+/).filter(w => w !== '');
  const b = after.split(/\s+/).filter(w => w !== '');
  const rows = a.length + 1;
  const cols = b.length + 1;
  const table = new Uint16Array(rows * cols);
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i * cols + j] =
        a[i] === b[j]
          ? (table[(i + 1) * cols + j + 1] ?? 0) + 1
          : Math.max(
              table[(i + 1) * cols + j] ?? 0,
              table[i * cols + j + 1] ?? 0,
            );
    }
  }
  const tokens: DiffToken[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      tokens.push({text: a[i] ?? '', op: 'same'});
      i++;
      j++;
    } else if (
      (table[(i + 1) * cols + j] ?? 0) >= (table[i * cols + j + 1] ?? 0)
    ) {
      tokens.push({text: a[i] ?? '', op: 'del'});
      i++;
    } else {
      tokens.push({text: b[j] ?? '', op: 'add'});
      j++;
    }
  }
  for (; i < a.length; i++) {
    tokens.push({text: a[i] ?? '', op: 'del'});
  }
  for (; j < b.length; j++) {
    tokens.push({text: b[j] ?? '', op: 'add'});
  }
  return tokens;
}

/**
 * The changes from 1 prompt version to the next: the system block rule by
 * rule, then the user template as 1 part.
 *
 * @param before The older version.
 * @param after The newer version.
 * @return The changes.
 */
export function diffVersions(
  before: {readonly system: string; readonly user: string | null},
  after: {readonly system: string; readonly user: string | null},
): PartChange[] {
  const changes = diffPrompt(before.system, after.system);
  const oldUser = oneLine([before.user ?? '']);
  const newUser = oneLine([after.user ?? '']);
  if (oldUser !== newUser) {
    changes.push({
      key: 'user',
      label: 'User message template',
      kind: 'changed',
      before: oldUser,
      after: newUser,
    });
  }
  return changes;
}
