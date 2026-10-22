import { NextResponse, type NextRequest } from 'next/server';

import { BASE_PATH } from '@/lib/format';
import { MIN_SECRET_LENGTH, UNLOCK_COOKIE, UNLOCK_MAX_AGE, passphraseMatches, signUnlock } from '@/lib/unlock';

// The founders' passphrase form (app/movers/unlock) posts here. On a match it
// sets the signed sv_founders cookie for /sv and sends the browser to the
// movers page; on a miss it waits about a second and sends it back to the form.
export const dynamic = 'force-dynamic';

const MAX_BODY = 4096;

/** A relative Location keeps the visitor on whichever host they came through
 * (induscore.site proxies /sv to this project). */
function seeOther(path: string): NextResponse {
  return new NextResponse(null, { status: 303, headers: { Location: `${BASE_PATH}${path}`, 'Cache-Control': 'no-store' } });
}

export async function POST(req: NextRequest) {
  let passphrase = '';
  if (Number(req.headers.get('content-length') ?? '0') <= MAX_BODY) {
    try {
      const value = (await req.formData()).get('passphrase');
      passphrase = typeof value === 'string' ? value : '';
    } catch {
      // not a form post
    }
  }
  const secret = process.env.SV_UNLOCK_SECRET ?? '';
  const ok = secret.length >= MIN_SECRET_LENGTH && passphraseMatches(passphrase, process.env.SV_FOUNDERS_PASSPHRASE_SHA256);
  if (!ok) {
    await new Promise((resolve) => setTimeout(resolve, 900 + Math.floor(Math.random() * 200)));
    return seeOther('/movers/unlock?failed=1');
  }
  const exp = Math.floor(Date.now() / 1000) + UNLOCK_MAX_AGE;
  const res = seeOther('/movers');
  res.cookies.set(UNLOCK_COOKIE, signUnlock(exp, secret), {
    httpOnly: true,
    secure: true,
    sameSite: 'strict',
    path: BASE_PATH,
    maxAge: UNLOCK_MAX_AGE,
  });
  return res;
}
