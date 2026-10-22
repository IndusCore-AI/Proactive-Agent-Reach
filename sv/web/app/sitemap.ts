import type { MetadataRoute } from 'next';

import { getDates, getSitemapData, getTopics } from '@/lib/api';
import { abs, storyPath } from '@/lib/format';

// Served at induscore.site/sv/sitemap.xml and listed in the apex robots.txt.
// Only pages with their own content: editions that carried stories, stories
// that made an edition, topics with enough stories to be indexable.
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [{ dates }, { items }, { topics }] = await Promise.all([getDates(), getSitemapData(), getTopics()]);
  const latest = dates[0]?.updated_at;
  return [
    { url: abs('/'), lastModified: latest, changeFrequency: 'daily', priority: 1 },
    { url: abs('/archive'), lastModified: latest, changeFrequency: 'daily', priority: 0.7 },
    { url: abs('/topics'), lastModified: latest, changeFrequency: 'daily', priority: 0.5 },
    { url: abs('/about'), changeFrequency: 'monthly', priority: 0.4 },
    ...dates.map((d) => ({ url: abs(`/${d.date}`), lastModified: d.updated_at, changeFrequency: 'weekly' as const, priority: 0.8 })),
    ...topics.filter((t) => t.count >= 3).map((t) => ({ url: abs(`/topics/${t.tag}`), lastModified: t.latest, changeFrequency: 'daily' as const, priority: 0.5 })),
    ...items.map((i) => ({ url: abs(storyPath(i)), lastModified: i.updated_at, changeFrequency: 'monthly' as const, priority: 0.6 })),
  ];
}
