import { apiHealth, getDates } from '@/lib/api';

export const dynamic = 'force-dynamic';

// Public and secret-free: is the site wired to its data, and how fresh is it?
export async function GET() {
  try {
    const [{ ok }, { dates }] = await Promise.all([apiHealth(), getDates()]);
    return Response.json(
      { site: 'ok', api: ok ? 'ok' : 'error', latest_edition: dates[0]?.date ?? null, latest_count: dates[0]?.count ?? 0, editions: dates.length },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  } catch {
    return Response.json({ site: 'ok', api: 'unreachable' }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
  }
}
