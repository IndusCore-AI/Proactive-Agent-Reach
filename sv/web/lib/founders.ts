import 'server-only';

import { cookies } from 'next/headers';

import { UNLOCK_COOKIE, verifyUnlock, type FounderKey } from './unlock';

/** The founder whose unlock cookie this request carries, or null. Reading
 * the cookie makes the page render per request, never from a shared cache, so
 * a page that calls this can show the desk only to the one browser that
 * unlocked it. The cookie is read first, unconditionally, so a missing secret
 * can never turn the page static. */
export async function currentFounder(): Promise<FounderKey | null> {
  const value = (await cookies()).get(UNLOCK_COOKIE)?.value;
  return verifyUnlock(value, process.env.SV_UNLOCK_SECRET, Math.floor(Date.now() / 1000));
}
