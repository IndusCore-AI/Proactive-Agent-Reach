import { getFeed } from '@/lib/api';
import { CATEGORY_LABEL, SITE_NAME, TAGLINE, abs, storyPath } from '@/lib/format';
import { esc } from '@/lib/xml';

// Rendered per request from the data cache (5 min, cleared on ingest), so a
// build never depends on the VM being reachable.
export const dynamic = 'force-dynamic';


// The latest edition as RSS 2.0. Each entry links to the original source and
// carries our story page as its guid.
export async function GET() {
  const feed = await getFeed({ limit: 100 });
  const items = feed.items
    .map((it) => {
      const desc = [it.summary, it.excerpt ? `“${it.excerpt}”` : null, `Source: ${it.source_name}.`].filter(Boolean).join(' ');
      return `<item>
  <title>${esc(it.title)}</title>
  <link>${esc(it.url)}</link>
  <guid isPermaLink="true">${esc(abs(storyPath(it)))}</guid>
  <category>${esc(CATEGORY_LABEL[it.category])}</category>
  ${it.published_at ? `<pubDate>${new Date(it.published_at).toUTCString()}</pubDate>` : ''}
  <source url="${esc(abs('/feed.xml'))}">${esc(it.source_name)}</source>
  <description>${esc(desc)}</description>
</item>`;
    })
    .join('\n');
  const body = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>${esc(SITE_NAME)}</title>
  <link>${abs('/')}</link>
  <description>${esc(TAGLINE)}</description>
  <language>en-us</language>
  <atom:link href="${abs('/feed.xml')}" rel="self" type="application/rss+xml"/>
  ${feed.run?.finished_at ? `<lastBuildDate>${new Date(feed.run.finished_at).toUTCString()}</lastBuildDate>` : ''}
${items}
</channel>
</rss>`;
  return new Response(body, { headers: { 'Content-Type': 'application/rss+xml; charset=utf-8' } });
}
