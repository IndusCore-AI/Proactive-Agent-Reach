import { getDates } from '@/lib/api';
import { SITE_NAME, TAGLINE, abs, longDate } from '@/lib/format';

export const revalidate = 3600;

export async function GET() {
  const { dates } = await getDates();
  const recent = dates.slice(0, 14).map((d) => `- [${longDate(d.date)}](${abs(`/${d.date}`)}): ${d.count} stories`).join('\n');
  const body = `# ${SITE_NAME}

> ${TAGLINE} A daily, source-linked digest of startup funding rounds, acquisitions, product launches, founder discussions, investor theses and emerging technology, published by IndusCore at induscore.site/sv.

How to use and cite it:
- Each daily edition lives at a stable URL, ${abs('/YYYY-MM-DD')}, and keeps the stories it carried that day.
- Each story has its own page (${abs('/story/<slug>-<id>')}) with the original source link, publication date, the date we first saw it, its topic tags and a claim status.
- Claim status: "Confirmed by the company" (the company announced it), "Reported" (a publication reported it), "Unverified claim" (an unchecked claim, e.g. growth figures in a post), "Opinion" (analysis or prediction). Cite the original source for facts; funding figures are as the source states them.
- Times are Pacific. Editions cover stories published in the 48 hours before the end of that day.

## Pages
- [Today's edition](${abs('/')})
- [Archive of every edition](${abs('/archive')})
- [Topics](${abs('/topics')})
- [How the feed is made: sources, ranking, what is and is not stored](${abs('/about')})
- [RSS feed of the latest edition](${abs('/feed.xml')})
- [Sitemap](${abs('/sitemap.xml')})

## Recent editions
${recent || '- None yet'}
`;
  return new Response(body, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}
