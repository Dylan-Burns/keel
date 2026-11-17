/**
 * The access mode of the service, from `GET /api/ready`: `token` needs a
 * Keel access token for every page; `public` lets a visitor in without one,
 * and the visitor asks with their own Anthropic API key. The access gate
 * reads it before any page renders; the tab keeps the last value so a page
 * load does not flash the token gate.
 */
import {getToken, readSession, writeSession} from './client';

/** The access mode of `/api/ready`. */
export type AccessMode = 'public' | 'token';

/** The session storage key of the last access mode the server reported. */
export const ACCESS_KEY = 'keel.access';

let mode: AccessMode | null = null;

/**
 * Reads an access mode value without trusting its type.
 *
 * @param value A value from the server or from storage.
 * @return The mode, or null for anything else.
 */
export function toAccessMode(value: unknown): AccessMode | null {
  return value === 'public' || value === 'token' ? value : null;
}

/**
 * The access mode the page follows: the one the server reported, else the
 * one the tab remembers, else `token`.
 *
 * @return The mode.
 */
export function getAccessMode(): AccessMode {
  return mode ?? toAccessMode(readSession(ACCESS_KEY)) ?? 'token';
}

/**
 * The access mode the tab remembers from an earlier page load.
 *
 * @return The mode, or null when the server has not reported one yet.
 */
export function knownAccessMode(): AccessMode | null {
  return mode ?? toAccessMode(readSession(ACCESS_KEY));
}

/**
 * Records the access mode the server reported.
 *
 * @param next The mode, or null to forget it (tests).
 */
export function setAccessMode(next: AccessMode | null): void {
  mode = next;
  writeSession(ACCESS_KEY, next);
}

/**
 * True for a visitor: a public service and no access token.
 *
 * @return Whether the page runs as a visitor.
 */
export function isVisitor(): boolean {
  return getAccessMode() === 'public' && getToken() === null;
}

/**
 * True when the page may call the API: it has a token, or the service is
 * public.
 *
 * @return Whether the API calls can pass.
 */
export function canCallApi(): boolean {
  return getToken() !== null || getAccessMode() === 'public';
}
