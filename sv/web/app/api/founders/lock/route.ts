import { NextResponse } from 'next/server';

import { BASE_PATH } from '@/lib/format';
import { UNLOCK_COOKIE } from '@/lib/unlock';

// "Lock" on the founders' view: clear the cookie on this browser. POST only,
// so a prefetch or a crawler following links can never sign anyone out.
export const dynamic = 'force-dynamic';

export function POST() {
  const res = new NextResponse(null, { status: 303, headers: { Location: `${BASE_PATH}/movers`, 'Cache-Control': 'no-store' } });
  res.cookies.set(UNLOCK_COOKIE, '', { httpOnly: true, secure: true, sameSite: 'strict', path: BASE_PATH, maxAge: 0 });
  return res;
}
