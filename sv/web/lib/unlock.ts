// The founders' unlock, as pure functions (no Next imports, so `npm test` runs
// them with node --test). lib/founders.ts reads the cookie; the route handlers
// under app/api/founders/ set and clear it.
//
// Cookie value: `${exp}.${who}.${hex(hmacSHA256(`${exp}.${who}`, SV_UNLOCK_SECRET))}`,
// where exp is a Unix time in seconds and who is the founder who unlocked
// (their votes and stage changes are recorded under that name). Rotating
// SV_UNLOCK_SECRET signs every founder out at once.
import { createHash, createHmac, timingSafeEqual } from 'node:crypto';

export const UNLOCK_COOKIE = 'sv_founders';
export const UNLOCK_MAX_AGE = 30 * 24 * 60 * 60; // seconds
/** Shortest SV_UNLOCK_SECRET accepted; anything weaker never unlocks. */
export const MIN_SECRET_LENGTH = 32;
const MAX_PASSPHRASE = 512;

/** Who can unlock. Lowercase names are what the API records as the voter. */
export const FOUNDERS = [
  { key: 'michael', name: 'Michael' },
  { key: 'pulkit', name: 'Pulkit' },
] as const;
export type FounderKey = (typeof FOUNDERS)[number]['key'];

export function isFounder(v: unknown): v is FounderKey {
  return typeof v === 'string' && FOUNDERS.some((f) => f.key === v);
}

export function founderName(key: string): string {
  return FOUNDERS.find((f) => f.key === key)?.name ?? key;
}

function hmacHex(payload: string, secret: string): string {
  return createHmac('sha256', secret).update(payload).digest('hex');
}

function sameHex(a: string, b: string): boolean {
  const x = Buffer.from(a, 'hex');
  const y = Buffer.from(b, 'hex');
  return x.length === y.length && x.length > 0 && timingSafeEqual(x, y);
}

export function signUnlock(exp: number, who: FounderKey, secret: string): string {
  return `${exp}.${who}.${hmacHex(`${exp}.${who}`, secret)}`;
}

/** The founder for a cookie this site signed with `secret` that has not
 * expired (and does not claim to live longer than a cookie we would ever
 * issue); null for anything else. */
export function verifyUnlock(value: string | undefined, secret: string | undefined, nowSeconds: number): FounderKey | null {
  if (!value || !secret || secret.length < MIN_SECRET_LENGTH) return null;
  const m = /^(\d{1,12})\.([a-z]{1,32})\.([0-9a-f]{64})$/.exec(value);
  if (!m || !isFounder(m[2])) return null;
  const exp = Number(m[1]);
  if (!Number.isSafeInteger(exp) || exp <= nowSeconds || exp > nowSeconds + UNLOCK_MAX_AGE + 60) return null;
  return sameHex(m[3], hmacHex(`${exp}.${m[2]}`, secret)) ? m[2] : null;
}

/** sha256(passphrase) against the configured hex digest, in constant time. */
export function passphraseMatches(passphrase: string, expectedSha256Hex: string | undefined): boolean {
  const want = (expectedSha256Hex ?? '').trim().toLowerCase(); // tolerate a pasted trailing newline
  if (!passphrase || passphrase.length > MAX_PASSPHRASE || !/^[0-9a-f]{64}$/.test(want)) return false;
  return sameHex(createHash('sha256').update(passphrase).digest('hex'), want);
}

/** Where a founders' form may send the browser back to: a path on the
 * movers pages only, never another site. */
export function safeReturn(v: unknown, fallback = '/movers'): string {
  if (typeof v !== 'string' || v.length > 300) return fallback;
  return /^\/movers(?:[/?#][^\s\\]*)?$/.test(v) && !v.startsWith('//') ? v : fallback;
}
