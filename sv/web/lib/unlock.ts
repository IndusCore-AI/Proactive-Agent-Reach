// The founders' unlock, as pure functions (no Next imports, so `npm test` runs
// them with node --test). lib/founders.ts reads the cookie; the route handlers
// under app/api/founders/ set and clear it.
//
// Cookie value: `${exp}.${hex(hmacSHA256(String(exp), SV_UNLOCK_SECRET))}`,
// where exp is a Unix time in seconds. Rotating SV_UNLOCK_SECRET signs every
// founder out at once.
import { createHash, createHmac, timingSafeEqual } from 'node:crypto';

export const UNLOCK_COOKIE = 'sv_founders';
export const UNLOCK_MAX_AGE = 30 * 24 * 60 * 60; // seconds
/** Shortest SV_UNLOCK_SECRET accepted; anything weaker never unlocks. */
export const MIN_SECRET_LENGTH = 32;
const MAX_PASSPHRASE = 512;

function hmacHex(exp: number, secret: string): string {
  return createHmac('sha256', secret).update(String(exp)).digest('hex');
}

function sameHex(a: string, b: string): boolean {
  const x = Buffer.from(a, 'hex');
  const y = Buffer.from(b, 'hex');
  return x.length === y.length && x.length > 0 && timingSafeEqual(x, y);
}

export function signUnlock(exp: number, secret: string): string {
  return `${exp}.${hmacHex(exp, secret)}`;
}

/** True only for a cookie this site signed with `secret` that has not expired
 * (and does not claim to live longer than a cookie we would ever issue). */
export function verifyUnlock(value: string | undefined, secret: string | undefined, nowSeconds: number): boolean {
  if (!value || !secret || secret.length < MIN_SECRET_LENGTH) return false;
  const m = /^(\d{1,12})\.([0-9a-f]{64})$/.exec(value);
  if (!m) return false;
  const exp = Number(m[1]);
  if (!Number.isSafeInteger(exp) || exp <= nowSeconds || exp > nowSeconds + UNLOCK_MAX_AGE + 60) return false;
  return sameHex(m[2], hmacHex(exp, secret));
}

/** sha256(passphrase) against the configured hex digest, in constant time. */
export function passphraseMatches(passphrase: string, expectedSha256Hex: string | undefined): boolean {
  if (!passphrase || passphrase.length > MAX_PASSPHRASE) return false;
  if (!expectedSha256Hex || !/^[0-9a-f]{64}$/i.test(expectedSha256Hex)) return false;
  return sameHex(createHash('sha256').update(passphrase).digest('hex'), expectedSha256Hex.toLowerCase());
}
