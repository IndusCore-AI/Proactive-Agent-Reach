import 'server-only';

export interface XPostData {
  id: string;
  author: string;
  handle: string;
  text: string;
  date: string;
  url: string;
}

const ENTITIES: Record<string, string> = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&mdash;': '—', '&nbsp;': ' ' };

function plain(html: string): string {
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&(amp|lt|gt|quot|#39|mdash|nbsp);/g, (m) => ENTITIES[m] ?? m)
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/** A post's author, text and date from X's public oEmbed endpoint, so the
 * card shows the real post even where X's widget never loads (blocked
 * scripts, privacy extensions). Cached for a day; null if X refuses. */
export async function getXPost(id: string): Promise<XPostData | null> {
  if (!/^\d{5,25}$/.test(id)) return null;
  try {
    const res = await fetch(
      `https://publish.twitter.com/oembed?omit_script=1&dnt=true&url=${encodeURIComponent(`https://twitter.com/i/status/${id}`)}`,
      { next: { revalidate: 86400 }, signal: AbortSignal.timeout(5000) },
    );
    if (!res.ok) return null;
    const d = (await res.json()) as { author_name?: string; author_url?: string; html?: string };
    const html = d.html ?? '';
    const body = /<p[^>]*>([\s\S]*?)<\/p>/i.exec(html)?.[1] ?? '';
    const links = [...html.matchAll(/<a href="([^"]+)">([^<]*)<\/a>/g)];
    const last = links[links.length - 1];
    const handle = (d.author_url ?? '').split('/').pop() ?? '';
    return {
      id,
      author: d.author_name ?? handle,
      handle,
      text: plain(body).replace(/\s*pic\.twitter\.com\/\S+$/, '').replace(/\s*https:\/\/t\.co\/\S+$/, ''),
      date: last ? plain(last[2]) : '',
      url: handle ? `https://x.com/${handle}/status/${id}` : `https://x.com/i/status/${id}`,
    };
  } catch {
    return null;
  }
}
