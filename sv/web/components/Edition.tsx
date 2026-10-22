import Link from 'next/link';

import { CATEGORIES, CATEGORY_LABEL, longDate, shortDate, storyPath, tagLabel, timePT, todayPT, abs, SITE_NAME } from '@/lib/format';
import type { Category, Feed, Item } from '@/lib/types';

import { HomeLink, JsonLd } from './Chrome';
import { StoryCard } from './StoryCard';

export const PAGE_SIZE = 100;

type Props = {
  feed: Feed;
  /** Path of this edition page: "/" for today, "/2026-10-22" for a date. */
  basePath: string;
  category?: Category;
  source?: string;
  page: number;
  notice?: React.ReactNode;
};

function editionHref(basePath: string, q: { category?: string; source?: string; page?: number }) {
  const p = new URLSearchParams();
  if (q.category) p.set('category', q.category);
  if (q.source) p.set('source', q.source);
  if (q.page && q.page > 1) p.set('page', String(q.page));
  const s = p.toString();
  return `${basePath}${s ? `?${s}` : ''}`;
}

function topTags(items: Item[], n = 10): [string, number][] {
  const counts = new Map<string, number>();
  for (const it of items) for (const t of it.tags) counts.set(t, (counts.get(t) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, n);
}

export function DatePicker({ value }: { value?: string }) {
  return (
    <form className="datepick" action="/sv/go" method="get">
      <label htmlFor="edition-date" className="sr-only">
        Choose an edition date
      </label>
      <input id="edition-date" type="date" name="date" defaultValue={value} min="2026-01-01" max={todayPT()} required />
      <button className="btn" type="submit">
        Go
      </button>
    </form>
  );
}

export function EditionView({ feed, basePath, category, source, page, notice }: Props) {
  const date = feed.date!;
  const filtered = Boolean(category || source);
  const cats = feed.facets.categories ?? {};
  const totalAll = Object.values(cats).reduce((a, b) => a + (b ?? 0), 0);
  const run = feed.run;
  const isToday = date === todayPT();
  const sourcesOk = run?.sources.filter((s) => s.ok).length ?? 0;
  const items = feed.items;

  // Unfiltered first page: the three highest-ranked stories lead, the rest
  // follow grouped by kind so funding, launches, news, discussion and analysis
  // never blur together.
  const lead = !filtered && page === 1 ? items.slice(0, 3) : [];
  const rest = !filtered && page === 1 ? items.slice(3) : items;
  const groups = CATEGORIES.map((c) => ({ ...c, items: rest.filter((i) => i.category === c.key) })).filter((g) => g.items.length);

  const pages = Math.max(1, Math.ceil(feed.total / PAGE_SIZE));
  const url = abs(basePath);

  return (
    <>
      <JsonLd
        data={{
          '@context': 'https://schema.org',
          '@type': 'CollectionPage',
          name: `${SITE_NAME}: ${longDate(date)}`,
          url,
          datePublished: run?.started_at ?? undefined,
          dateModified: run?.finished_at ?? undefined,
          isPartOf: { '@type': 'WebSite', name: SITE_NAME, url: abs('/') },
          publisher: { '@type': 'Organization', name: 'IndusCore', url: 'https://induscore.site' },
          mainEntity: {
            '@type': 'ItemList',
            numberOfItems: feed.total,
            itemListElement: items.slice(0, 50).map((it, i) => ({
              '@type': 'ListItem',
              position: i + 1,
              url: abs(storyPath(it)),
              name: it.title,
            })),
          },
        }}
      />
      <div className="edition">
        <div>
          <h2 className="edition-date">
            {isToday ? 'Today · ' : ''}
            {longDate(date)}
          </h2>
          <p className="edition-meta">
            <span className={`fresh${isToday ? '' : ' stale'}`}>
              {totalAll} {totalAll === 1 ? 'story' : 'stories'}
              {run?.finished_at ? `, compiled ${timePT(run.finished_at)}` : ''}
              {run && run.sources.length > 0 ? ` from ${sourcesOk} of ${run.sources.length} sources` : ''}
              {run?.status === 'partial' ? ' (some sources failed)' : ''}
            </span>
          </p>
        </div>
        <nav className="datenav" aria-label="Editions">
          <Link className="btn" href={feed.prev ? `/${feed.prev}` : '#'} aria-disabled={!feed.prev} rel="prev">
            ← {feed.prev ? shortDate(feed.prev) : 'Earlier'}
          </Link>
          {feed.next ? (
            <Link className="btn" href={`/${feed.next}`} rel="next">
              {shortDate(feed.next)} →
            </Link>
          ) : !isToday ? (
            <HomeLink className="btn">Today →</HomeLink>
          ) : null}
          <DatePicker value={date} />
        </nav>
      </div>
      {notice}
      <div className="layout">
        <main id="main">
          <ul className="chips" aria-label="Filter by kind">
            <li>
              <Link className="chip" href={editionHref(basePath, {})} aria-current={!filtered ? 'true' : undefined}>
                All <span className="n">{totalAll}</span>
              </Link>
            </li>
            {CATEGORIES.filter((c) => cats[c.key]).map((c) => (
              <li key={c.key}>
                <Link className="chip" href={editionHref(basePath, { category: c.key })} aria-current={category === c.key ? 'true' : undefined} rel="nofollow">
                  {c.plural} <span className="n">{cats[c.key]}</span>
                </Link>
              </li>
            ))}
          </ul>
          {filtered && (
            <p className="edition-meta">
              Showing {feed.total} {category ? CATEGORY_LABEL[category].toLowerCase() : ''} {source ? `from ${feed.facets.sources?.[source]?.name ?? source}` : ''}{' '}
              {feed.total === 1 ? 'story' : 'stories'} from this edition. <Link href={editionHref(basePath, {})}>Show all</Link>
            </p>
          )}
          {items.length === 0 && <p className="empty">Nothing matches this filter in this edition.</p>}
          {lead.length > 0 && (
            <section className="section" aria-labelledby="top">
              <div className="section-head">
                <h2 id="top">Top stories</h2>
                <span>Ranked by recency, engagement and source signal</span>
              </div>
              <ul className="stories lead">
                {lead.map((it) => (
                  <StoryCard key={it.id} item={it} headingLevel={3} />
                ))}
              </ul>
            </section>
          )}
          {!filtered && page === 1
            ? groups.map((g) => (
                <section className="section" key={g.key} aria-labelledby={`g-${g.key}`}>
                  <div className="section-head">
                    <h2 id={`g-${g.key}`}>{g.plural}</h2>
                    <span>{g.items.length}</span>
                  </div>
                  <ul className="stories">
                    {g.items.map((it) => (
                      <StoryCard key={it.id} item={it} />
                    ))}
                  </ul>
                </section>
              ))
            : items.length > 0 && (
                <ul className="stories">
                  {items.map((it) => (
                    <StoryCard key={it.id} item={it} />
                  ))}
                </ul>
              )}
          {pages > 1 && (
            <nav className="pager" aria-label="Pages">
              {page > 1 ? <Link className="btn" href={editionHref(basePath, { category, source, page: page - 1 })}>← Previous page</Link> : <span />}
              {page < pages ? <Link className="btn" href={editionHref(basePath, { category, source, page: page + 1 })}>Next page →</Link> : <span />}
            </nav>
          )}
        </main>
        <aside className="rail" aria-label="About this edition">
          {run && run.sources.length > 0 && (
            <section className="panel">
              <h2>Where these came from</h2>
              <ul>
                {run.sources
                  .filter((s) => (s.kept ?? 0) > 0)
                  .sort((a, b) => (b.kept ?? 0) - (a.kept ?? 0))
                  .map((s) => (
                    <li key={s.source}>
                      <Link href={editionHref(basePath, { source: s.source })} rel="nofollow">
                        {s.name ?? s.source}
                      </Link>
                      <span>{s.kept}</span>
                    </li>
                  ))}
              </ul>
              <details className="sources-all">
                <summary>
                  {sourcesOk} of {run.sources.length} sources answered
                </summary>
                <ul>
                  {run.sources.map((s) => (
                    <li key={s.source}>
                      <span>{s.name ?? s.source}</span>
                      <span className={s.ok ? undefined : 'src-fail'}>{s.ok ? `${s.kept ?? 0} kept` : 'unavailable'}</span>
                    </li>
                  ))}
                </ul>
              </details>
            </section>
          )}
          {topTags(items).length > 0 && (
            <section className="panel">
              <h2>Topics in this edition</h2>
              <ul>
                {topTags(items).map(([t, n]) => (
                  <li key={t}>
                    <Link href={`/topics/${t}`}>{tagLabel(t)}</Link>
                    <span>{n}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section className="panel">
            <h2>How to read this</h2>
            <p>
              Titles link to the original source. <b>Confirmed</b> means the company said it; <b>Reported</b> means a
              publication reported it; <b>Unverified</b> marks a claim nobody independent has checked.{' '}
              <Link href="/about">Methodology</Link>
            </p>
          </section>
        </aside>
      </div>
    </>
  );
}
