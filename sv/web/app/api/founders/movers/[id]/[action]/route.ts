import { revalidateTag } from 'next/cache';
import { NextResponse, type NextRequest } from 'next/server';

import { CACHE_TAG, deskAction } from '@/lib/api';
import { currentFounder } from '@/lib/founders';
import { BASE_PATH, MOVER_ID_RE } from '@/lib/format';
import { safeReturn } from '@/lib/unlock';

// The desk's forms post here: a vote (with an optional reason), a stage, or a
// status (publish, pass, back to the queue). Plain form posts, so they work
// without JavaScript. Who acted comes from the signed unlock cookie, never
// from the form. The cookie is SameSite=Strict, and a request the browser
// marks cross-site is refused before anything else.
export const dynamic = 'force-dynamic';

const MAX_BODY = 4096;
const STAGES = new Set(['new', 'researching', 'building', 'passed']);
const STATUSES = new Set(['proposed', 'watching', 'archived']);

function back(path: string, failed = false): NextResponse {
  const [base, hash = ''] = path.split('#');
  const url = failed ? `${base}${base.includes('?') ? '&' : '?'}failed=1` : base;
  return new NextResponse(null, {
    status: 303,
    headers: { Location: `${BASE_PATH}${url}${hash ? `#${hash}` : ''}`, 'Cache-Control': 'no-store' },
  });
}

function text(form: FormData, key: string): string {
  const v = form.get(key);
  return typeof v === 'string' ? v.trim() : '';
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string; action: string }> }) {
  const { id, action } = await ctx.params;
  if (req.headers.get('sec-fetch-site') === 'cross-site') return new NextResponse(null, { status: 403 });
  const who = await currentFounder();
  if (!who) return back('/movers/unlock');
  if (!MOVER_ID_RE.test(id) || !['vote', 'stage', 'status'].includes(action)) return new NextResponse(null, { status: 404 });
  if (Number(req.headers.get('content-length') ?? '0') > MAX_BODY) return new NextResponse(null, { status: 413 });

  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return new NextResponse(null, { status: 400 });
  }
  const to = safeReturn(text(form, 'back'), `/movers/${id}`);

  let body: Record<string, unknown> | null = null;
  if (action === 'vote') {
    const vote = Number(text(form, 'vote'));
    if ([1, -1, 0].includes(vote)) body = { voter: who, vote, reason: text(form, 'reason').slice(0, 500) || null };
  } else if (action === 'stage') {
    const stage = text(form, 'stage');
    if (STAGES.has(stage)) body = { voter: who, stage };
  } else {
    const status = text(form, 'status');
    if (STATUSES.has(status)) body = { voter: who, status };
  }
  if (!body) return back(to, true);

  const status = await deskAction(id, action as 'vote' | 'stage' | 'status', body);
  if (status !== 200) return back(to, true);
  // Publishing or taking a mover off the list changes public pages.
  if (action === 'status') revalidateTag(CACHE_TAG);
  return back(to);
}
