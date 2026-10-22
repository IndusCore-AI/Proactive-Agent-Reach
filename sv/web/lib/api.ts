import 'server-only';

import { createHmac, timingSafeEqual } from 'node:crypto';

import type { Feed, Item, ItemDetail } from './types';

// The VM API is reachable only through a Cloudflare quick tunnel whose
// hostname changes when the tunnel restarts. The VM announces the current URL
// on an ntfy topic, HMAC-signed with SV_ANNOUNCE_SECRET; we trust only a
// correctly signed *.trycloudflare.com URL and fall back to SV_API_URL.
const TUNNEL_RE = /^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/;
const REVALIDATE_SECONDS = 300;
export const CACHE_TAG = 'sv';

let cachedBase: { url: string; at: number } | null = null;

function verify(url: string, ts: number, sig: string, secret: string): boolean {
  const want = createHmac('sha256', secret).update(`${url}|${ts}`).digest();
  const got = Buffer.from(sig, 'hex');
  return got.length === want.length && timingSafeEqual(got, want);
}

async function discover(): Promise<string | null> {
  const topic = process.env.SV_NTFY_TOPIC;
  const secret = process.env.SV_ANNOUNCE_SECRET;
  if (!topic || !secret) return null;
  try {
    const res = await fetch(`https://ntfy.sh/${encodeURIComponent(topic)}/json?poll=1&since=all`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    let best: { url: string; ts: number } | null = null;
    for (const line of (await res.text()).split('\n')) {
      if (!line.trim()) continue;
      try {
        const msg = JSON.parse(line);
        if (msg.event !== 'message') continue;
        const { url, ts, sig } = JSON.parse(msg.message);
        if (typeof url !== 'string' || !TUNNEL_RE.test(url) || typeof ts !== 'number' || typeof sig !== 'string') continue;
        if (!verify(url, ts, sig, secret)) continue;
        if (!best || ts > best.ts) best = { url, ts };
      } catch {
        // someone else's message on the topic; ignore it
      }
    }
    return best?.url ?? null;
  } catch {
    return null;
  }
}

async function apiBase(refresh = false): Promise<string> {
  if (!refresh && cachedBase && Date.now() - cachedBase.at < 10 * 60_000) return cachedBase.url;
  const url = (await discover()) ?? process.env.SV_API_URL ?? null;
  if (!url) throw new Error('Feed API location is not configured');
  cachedBase = { url, at: Date.now() };
  return url;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  const token = process.env.SV_READ_TOKEN;
  if (!token) throw new Error('SV_READ_TOKEN is not set');
  for (const refresh of [false, true]) {
    let res: Response;
    try {
      res = await fetch(`${await apiBase(refresh)}${path}`, {
        headers: { Authorization: `Bearer ${token}` },
        next: { revalidate: REVALIDATE_SECONDS, tags: [CACHE_TAG] },
        signal: AbortSignal.timeout(8000),
      });
    } catch (err) {
      if (!refresh) continue; // tunnel moved or is restarting: look it up again once
      throw err;
    }
    if (res.ok) return (await res.json()) as T;
    if (res.status === 404) throw new ApiError(404, 'not found');
    // A dead quick tunnel answers 530 from Cloudflare's edge.
    if (!refresh && res.status >= 500) continue;
    throw new ApiError(res.status, `feed API answered ${res.status}`);
  }
  throw new ApiError(502, 'feed API unreachable');
}

/** Forward an ingest call to the VM. The caller's own ingest token is passed
 * through untouched; this server holds no write credential. */
export async function forwardIngest(method: 'GET' | 'POST', path: string, auth: string, body?: string): Promise<Response> {
  for (const refresh of [false, true]) {
    try {
      const res = await fetch(`${await apiBase(refresh)}/v1/ingest/${path}`, {
        method,
        headers: { Authorization: auth, 'Content-Type': 'application/json' },
        body,
        cache: 'no-store',
        signal: AbortSignal.timeout(50_000),
      });
      if (res.status === 530 && !refresh) continue;
      return res;
    } catch (err) {
      if (refresh) throw err;
    }
  }
  throw new ApiError(502, 'feed API unreachable');
}

export async function apiHealth(): Promise<{ ok: boolean }> {
  const res = await fetch(`${await apiBase(true)}/v1/health`, { cache: 'no-store', signal: AbortSignal.timeout(8000) });
  return { ok: res.ok };
}

type FeedQuery = { date?: string; category?: string; source?: string; tag?: string; limit?: number; offset?: number };

export function getFeed(q: FeedQuery = {}): Promise<Feed> {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== '') p.set(k, String(v));
  return get<Feed>(`/v1/feed?${p}`);
}

export function getDates(): Promise<{ dates: { date: string; count: number; updated_at: string }[] }> {
  return get('/v1/dates');
}

export function getItem(id: string): Promise<ItemDetail> {
  return get(`/v1/items/${encodeURIComponent(id)}`);
}

export function getTopics(): Promise<{ topics: { tag: string; count: number; latest: string }[] }> {
  return get('/v1/topics');
}

export function getTopic(tag: string, offset = 0): Promise<{ tag: string; total: number; items: Item[] }> {
  return get(`/v1/topics/${encodeURIComponent(tag)}?limit=40&offset=${offset}`);
}

export function search(q: string): Promise<{ q: string; total: number; items: Item[] }> {
  return get(`/v1/search?${new URLSearchParams({ q, limit: '40' })}`);
}

export function getSitemapData(): Promise<{ items: { id: string; title: string; updated_at: string; date: string }[] }> {
  return get('/v1/sitemap');
}
