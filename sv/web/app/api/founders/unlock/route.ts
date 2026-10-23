import { NextResponse, type NextRequest } from 'next/server';

import { BASE_PATH } from '@/lib/format';
import { MIN_SECRET_LENGTH, UNLOCK_COOKIE, UNLOCK_MAX_AGE, isFounder, passphraseMatches, signUnlock } from '@/lib/unlock';

// The founders' passphrase form (app/movers/unlock) posts here, with who is
// unlocking. On a match it sets the signed sv_founders cookie (carrying that
// name) for /sv and sends the browser to the desk; on a miss it waits about a
// second and sends it back to the form.
export const dynamic = 'force-dynamic';

const MAX_BODY = 4096;

/** A relative Location keeps the visitor on whichever host they came through
 * (induscore.site proxies /sv to this project). */
function seeOther(path: string): NextResponse {
  return new NextResponse(null, { status: 303, headers: { Location: `${BASE_PATH}${path}`, 'Cache-Control': 'no-store' } });
}

export async function POST(req: NextRequest) {
  let passphrase = '';
  let who: unknown = null;
  if (Number(req.headers.get('content-length') ?? '0') <= MAX_BODY) {
    try {
      const form = await req.formData();
      const value = form.get('passphrase');
      passphrase = typeof value === 'string' ? value : '';
      who = form.get('who');
    } catch {
      // not a form post
    }
  }
  const secret = process.env.SV_UNLOCK_SECRET ?? '';
  const ok = secret.length >= MIN_SECRET_LENGTH && passphraseMatches(passphrase, process.env.SV_FOUNDERS_PASSPHRASE_SHA256);
  if (!ok || !isFounder(who)) {
    await new Promise((resolve) => setTimeout(resolve, 900 + Math.floor(Math.random() * 200)));
    return seeOther('/movers/unlock?failed=1');
  }
  const exp = Math.floor(Date.now() / 1000) + UNLOCK_MAX_AGE;
  const res = seeOther('/movers');
  res.cookies.set(UNLOCK_COOKIE, signUnlock(exp, who, secret), {
    httpOnly: true,
    secure: true,
    sameSite: 'strict',
    path: BASE_PATH,
    maxAge: UNLOCK_MAX_AGE,
  });
  return res;
}
