import type { NextRequest } from 'next/server';

import { BASE_PATH, FIRST_EDITION, isIsoDate, todayPT } from '@/lib/format';

// The date picker is a plain GET form, so it works without JavaScript. A
// relative Location keeps the visitor on whichever host they came through.
export function GET(req: NextRequest) {
  const date = req.nextUrl.searchParams.get('date') ?? '';
  const target = isIsoDate(date) && date >= FIRST_EDITION && date <= todayPT() ? `/${date}` : '/archive';
  return new Response(null, { status: 303, headers: { Location: `${BASE_PATH}${target}`, 'Cache-Control': 'no-store' } });
}
