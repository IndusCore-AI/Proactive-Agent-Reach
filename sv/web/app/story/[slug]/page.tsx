import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound, permanentRedirect } from 'next/navigation';

import { Bar, HomeLink, JsonLd } from '@/components/Chrome';
import { YouTubeEmbed } from '@/components/Embeds';
import { Card, XPost } from '@/components/Cards';
import { LocalTime } from '@/components/LocalTime';
import { Thumb } from '@/components/Thumb';
import { ApiError, getItem } from '@/lib/api';
import {
  CATEGORY_LABEL, CLAIM_LABEL, SITE_NAME, abs, compactNumber, fundingLine, hostOf, idFromSlug, longDate, moverPath,
  storyPath, tagLabel,
} from '@/lib/format';
import type { ItemDetail } from '@/lib/types';

type Params = Promise<{ slug: string }>;

const CLAIM_EXPLAINED = {
  confirmed: 'The company itself announced or confirmed this.',
  reported: 'A publication reported this; the company may not have confirmed it.',
  unverified: 'A claim made in a post or discussion that nobody independent has verified.',
  opinion: 'Commentary or analysis: someone’s view, not a reported fact.',
} as const;

async function load(slug: string): Promise<ItemDetail> {
  const id = idFromSlug(slug);
  if (!id) notFound();
  try {
    return await getItem(id);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 422)) notFound();
    throw err;
  }
}

function describe(item: ItemDetail): string {
  const text = item.summary ?? item.excerpt ?? `${CATEGORY_LABEL[item.category]} from ${item.source_name}.`;
  return `${text} Source: ${item.source_name}.`.slice(0, 300);
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const item = await load((await params).slug);
  const url = abs(storyPath(item));
  return {
    title: item.title,
    description: describe(item),
    alternates: { canonical: url },
    openGraph: { title: item.title, description: describe(item), url, type: 'website' },
    twitter: { title: item.title, description: describe(item) },
    // A story that never made it into an edition is not a page worth indexing.
    robots: item.feed_date ? undefined : { index: false, follow: true },
  };
}

export default async function StoryPage({ params }: { params: Params }) {
  const { slug } = await params;
  const item = await load(slug);
  const canonical = storyPath(item);
  if (`/story/${slug}` !== canonical) permanentRedirect(canonical);

  const mentions = (item.mentions ?? []).filter((m) => m.url !== item.url);
  const detail = item.score_detail as Record<string, unknown> | null;
  const why = detail && typeof detail.why === 'string' ? detail.why : null;

  return (
    <>
      <Bar />
      <JsonLd
        data={{
          '@context': 'https://schema.org',
          '@graph': [
            {
              '@type': 'WebPage',
              '@id': abs(canonical),
              url: abs(canonical),
              name: item.title,
              description: describe(item),
              datePublished: item.discovered_at,
              dateModified: item.updated_at,
              isPartOf: { '@type': 'WebSite', name: SITE_NAME, url: abs('/') },
              keywords: item.tags.map(tagLabel).join(', ') || undefined,
              isBasedOn: {
                '@type': 'CreativeWork',
                url: item.url,
                name: item.title,
                datePublished: item.published_at ?? undefined,
                publisher: { '@type': 'Organization', name: item.source_name },
                author: item.author ? { '@type': 'Person', name: item.author } : undefined,
              },
            },
            {
              '@type': 'BreadcrumbList',
              itemListElement: [
                { '@type': 'ListItem', position: 1, name: SITE_NAME, item: abs('/') },
                ...(item.feed_date ? [{ '@type': 'ListItem', position: 2, name: longDate(item.feed_date), item: abs(`/${item.feed_date}`) }] : []),
                { '@type': 'ListItem', position: item.feed_date ? 3 : 2, name: item.title, item: abs(canonical) },
              ],
            },
          ],
        }}
      />
      <div className="wrap">
        <ol className="crumbs">
          <li>
            <HomeLink>Today</HomeLink>
          </li>
          {item.feed_date && (
            <li>
              <Link href={`/${item.feed_date}#s-${item.id}`}>Edition of {longDate(item.feed_date)}</Link>
            </li>
          )}
          <li aria-current="page">{CATEGORY_LABEL[item.category]}</li>
        </ol>
        <main id="main" className="detail">
          <a className="detail-pic" href={item.url} rel="noopener" target="_blank" tabIndex={-1} aria-hidden="true">
            <Thumb src={item.image_url} kind={item.image_kind} publisher={item.source_name} category={item.category} eager />
          </a>
          <div className="labels">
            <span className={`cat cat-${item.category}`}>{CATEGORY_LABEL[item.category]}</span>
            <span className={`claim claim-${item.claim_status}`}>{CLAIM_LABEL[item.claim_status]}</span>
          </div>
          <h1 className="story-title">{item.title}</h1>
          <p className="byline">
            <span className="pub">{item.source_name}</span>
            {item.author && <span>by {item.author}</span>}
            {item.published_at && <LocalTime ts={item.published_at} />}
          </p>
          {item.summary && (
            <p className="context">
              <b>Context:</b> {item.summary}
            </p>
          )}
          {item.excerpt && (
            <p className="excerpt">
              From {item.source_name}: <q>{item.excerpt}</q>
            </p>
          )}
          {item.funding && (
            <p className="facts">
              {fundingLine(item.funding)}
              <small>As stated by {item.source_name}.</small>
            </p>
          )}
          {item.embed?.type === 'x' && <XPost id={item.embed.ref} title={item.title} />}
          {item.embed?.type === 'youtube' && <YouTubeEmbed id={item.embed.ref} title={item.title} />}
          <div className="cta">
            <a className="btn primary" href={item.url} rel="noopener" target="_blank">
              Read the original at {hostOf(item.url)} ↗
            </a>
            {mentions.slice(0, 4).map((m) => (
              <a className="btn" key={m.url} href={m.url} rel="noopener" target="_blank">
                {m.label} ↗
                {m.points != null ? ` · ${compactNumber(m.points)} pts` : ''}
                {m.comments != null ? ` · ${compactNumber(m.comments)} comments` : ''}
              </a>
            ))}
          </div>
          {item.movers && item.movers.length > 0 && (
            <ul className="chips mover-chips" aria-label="Movers this story is about">
              {item.movers.map((m) => (
                <li key={m.id}>
                  <Link className="chip" href={moverPath(m.id)}>
                    Mover: {m.name}
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <dl>
            <dt>Source</dt>
            <dd>
              {item.source_name} ({hostOf(item.url)})
            </dd>
            <dt>Published</dt>
            <dd>{item.published_at ? <LocalTime ts={item.published_at} /> : 'The source gives no date'}</dd>
            <dt>First seen here</dt>
            <dd>
              <LocalTime ts={item.discovered_at} />
            </dd>
            {item.feed_date && (
              <>
                <dt>Edition</dt>
                <dd>
                  <Link href={`/${item.feed_date}`}>{longDate(item.feed_date)}</Link>
                  {item.rank ? `, ranked ${item.rank}` : ''}
                </dd>
              </>
            )}
            <dt>Status</dt>
            <dd>{CLAIM_EXPLAINED[item.claim_status]}</dd>
            {mentions.some((m) => m.points != null || m.comments != null) && (
              <>
                <dt>Engagement</dt>
                <dd>As shown by each platform when we last looked (<LocalTime ts={mentions[0].observed_at} />).</dd>
              </>
            )}
            {why && (
              <>
                <dt>Why it’s here</dt>
                <dd>{why}</dd>
              </>
            )}
            {item.tags.length > 0 && (
              <>
                <dt>Topics</dt>
                <dd>
                  {item.tags.map((t, i) => (
                    <span key={t}>
                      {i > 0 && ', '}
                      <Link href={`/topics/${t}`}>{tagLabel(t)}</Link>
                    </span>
                  ))}
                </dd>
              </>
            )}
          </dl>
        </main>
        {item.related.length > 0 && (
          <section className="section" aria-labelledby="related" style={{ paddingBottom: 48 }}>
            <div className="section-head">
              <h2 id="related">Related stories</h2>
            </div>
            <div className="grid">
              {item.related.slice(0, 6).map((r) => (
                <Card key={r.id} item={r} showEdition />
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  );
}
