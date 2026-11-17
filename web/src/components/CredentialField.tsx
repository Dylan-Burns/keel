import type {JSX} from 'react';

import {getAccessMode} from '../api/access';
import {ApiKeySettings} from './ApiKeySettings';
import type {TokenFieldProps} from './TokenField';
import {TokenField} from './TokenField';

/**
 * The credential control of a top bar: on a public service the API key
 * settings (with the admin sign in), else the access token field.
 *
 * @param props The props of the token field.
 * @return The control.
 */
export function CredentialField(props: TokenFieldProps): JSX.Element {
  return getAccessMode() === 'public' ? (
    <ApiKeySettings />
  ) : (
    <TokenField {...props} />
  );
}
