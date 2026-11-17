import {motion, useReducedMotion} from 'motion/react';
import type {JSX} from 'react';
import {useSyncExternalStore} from 'react';

import {getApiKey, openApiKeySettings, subscribeApiKey} from '../api/apiKey';
import {banner, pick} from '../motion/presets';

/** Props of ApiKeyPrompt. */
export interface ApiKeyPromptProps {
  /**
   * The error code: `api_key_required`, `invalid_api_key`, or
   * `provider_auth_rejected`.
   */
  readonly code: string;
  /** Asks the question again; null when there is none to ask. */
  readonly onRetry: (() => void) | null;
  readonly retryEnabled: boolean;
}

/** The text of `api_key_required`, and of an unknown code. */
const KEY_REQUIRED: readonly [string, string] = [
  'Add your Anthropic API key to ask this question.',
  'New questions run on your own key. The example questions answer without one.',
];

/** The text of each code: the headline and the line under it. */
const TEXT: Readonly<Record<string, readonly [string, string]>> = {
  api_key_required: KEY_REQUIRED,
  invalid_api_key: [
    'This API key is not an Anthropic key.',
    'A key starts with sk-ant-. Check it in the API key settings.',
  ],
  provider_auth_rejected: [
    'Anthropic rejected the API key.',
    'Check the key in the API key settings, or replace it, then ask again.',
  ],
};

/**
 * The inline prompt for an API key, in place of the provider banner: the
 * question needs the visitor's own key, the key is malformed, or Anthropic
 * refused it. Its button opens the API key settings of the top bar; once a
 * key is stored, Ask again sends the question.
 *
 * @param props The code and the retry action.
 * @return The prompt.
 */
export function ApiKeyPrompt({
  code,
  onRetry,
  retryEnabled,
}: ApiKeyPromptProps): JSX.Element {
  const reduced = useReducedMotion();
  const key = useSyncExternalStore(subscribeApiKey, getApiKey);
  const [title, line] = TEXT[code] ?? KEY_REQUIRED;
  return (
    <motion.div
      variants={pick(banner.slide, reduced)}
      initial="hidden"
      animate="visible"
      role="alert"
      className="notice notice-warn flex flex-wrap items-center gap-3 text-[13px]"
      data-testid="api-key-prompt"
      data-code={code}
    >
      <span className="min-w-0 flex-1">
        <strong className="font-semibold text-ink">{title}</strong>{' '}
        <span className="text-ink-2">{line}</span>
      </span>
      <button
        type="button"
        className="btn btn-primary"
        data-testid="api-key-prompt-open"
        onClick={openApiKeySettings}
      >
        {key === null ? 'Add API key' : 'Check API key'}
      </button>
      {onRetry !== null && key !== null && (
        <button
          type="button"
          className="btn"
          disabled={!retryEnabled}
          onClick={onRetry}
        >
          Ask again
        </button>
      )}
    </motion.div>
  );
}
