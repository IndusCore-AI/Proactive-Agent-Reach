import { revalidateTag } from 'next/cache';
import type { NextRequest } from 'next/server';

import { CACHE_TAG, forwardIngest } from '@/lib/api';

// The Claude Code aggregation run talks to this stable URL; it forwards to the
// VM API with the caller's own ingest token, which the VM checks. This server
// holds no write credential. A successful write clears the feed cache so the
// site shows new stories on the next request, without a redeploy.
export const dynamic = 'force-dynamic';
export const maxDuration = 60;

const SEGMENT = /^[a-z0-9-]{1,64}$/;
const MAX_BODY = 1_000_000;

async function handle(req: NextRequest, params: Promise<{ path: string[] }>, method: 'GET' | 'POST') {
  const { path } = await params;
  const auth = req.headers.get('authorization') ?? '';
  if (!auth.startsWith('Bearer ')) return Response.json({ detail: 'missing bearer token' }, { status: 401 });
  if (!path.length || path.length > 4 || !path.every((s) => SEGMENT.test(s))) {
    return Response.json({ detail: 'unsupported path' }, { status: 404 });
  }
  let body: string | undefined;
  if (method === 'POST') {
    body = await req.text();
    if (body.length > MAX_BODY) return Response.json({ detail: 'payload too large' }, { status: 413 });
    try {
      JSON.parse(body);
    } catch {
      return Response.json({ detail: 'body must be JSON' }, { status: 400 });
    }
  }
  try {
    const res = await forwardIngest(method, path.join('/'), auth, body);
    const text = await res.text();
    if (method === 'POST' && res.ok) revalidateTag(CACHE_TAG);
    return new Response(text, { status: res.status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
  } catch {
    return Response.json({ detail: 'feed API unreachable' }, { status: 502 });
  }
}

export function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return handle(req, ctx.params, 'GET');
}

export function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return handle(req, ctx.params, 'POST');
}
