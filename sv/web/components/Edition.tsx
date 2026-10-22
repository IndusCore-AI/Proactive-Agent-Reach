import Link from 'next/link';

import { CATEGORIES, CATEGORY_LABEL, longDate, shortDate, storyPath, timePT, todayPT, abs, SITE_NAME } from '@/lib/format';
import type { Category, Feed, Item } from '@/lib/types';

import { HomeLink, JsonLd } from './Chrome';
import { Card, CompactRow, EmbedCard, HeroCard } from './Cards';

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

const SECTION_MAX = 6;

function Grid({ items }: { items: Item[] }) {
  const rows = items.filter((i) => i.category === 'discussion');
  const cards = items.filter((i) => i.category !== 'discussion');
  return (
    <>
      {cards.length > 0 && (
        <div className="grid">
          {cards.map((it) => (
            <Card key={it.id} item={it} />
          ))}
        </div>
      )}
      {rows.length > 0 && (
        <div className="rows">
          {rows.map((it) => (
            <CompactRow key={it.id} item={it} />
          ))}
        </div>
      )}
    </>
  );
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
  const front = !filtered && page === 1;

  // Front page: the lead story and three more up top, then the posts and
  // videos the day's stories are about, then each kind in its own section
  // (six at most, the rest one click away). Nothing is shown twice.
  const shown = new Set<string>();
  const take = (list: Item[]) => {
    list.forEach((i) => shown.add(i.id));
    return list;
  };
  const lead = front ? take(items.slice(0, 4)) : [];
  const watch = front ? take(items.filter((i) => i.embed && !shown.has(i.id)).slice(0, 6)) : [];
  const leadEmbeds = front ? lead.filter((i) => i.embed) : [];
  const groups = front
    ? CATEGORIES.map((c) => {
        const all = items.filter((i) => i.category === c.key && !shown.has(i.id));
        return { ...c, all, items: all.slice(0, c.key === 'discussion' ? 8 : SECTION_MAX) };
      }).filter((g) => g.items.length)
    : [];
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
              {run?.finished_at ? ` · updated ${timePT(run.finished_at).replace(/^[A-Z][a-z]{2} \d+, /, '')}` : ''}
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
      <main id="main" className="front">
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
            {feed.total} {category ? CATEGORY_LABEL[category].toLowerCase() : ''} {source ? `from ${run?.sources.find((s) => s.source === source)?.name ?? source}` : ''}{' '}
            {feed.total === 1 ? 'story' : 'stories'} in this edition · <Link href={editionHref(basePath, {})}>Show all</Link>
          </p>
        )}
        {items.length === 0 && <p className="empty">Nothing matches this filter in this edition.</p>}

        {lead.length > 0 && (
          <section className="section" aria-labelledby="top">
            <h2 id="top" className="sr-only">
              Top stories
            </h2>
            <div className="lead">
              <HeroCard item={lead[0]} />
              <div className="lead-side">
                {lead.slice(1).map((it) => (
                  <Card key={it.id} item={it} />
                ))}
              </div>
            </div>
          </section>
        )}

        {watch.length + leadEmbeds.length > 0 && (
          <section className="section watch" aria-labelledby="watch">
            <div className="section-head">
              <h2 id="watch">Watch and posts</h2>
              <span>From the people and companies in today&apos;s stories</span>
            </div>
            <div className="embed-grid">
              {[...leadEmbeds, ...watch].map((it) => (
                <EmbedCard key={it.id} item={it} />
              ))}
            </div>
          </section>
        )}

        {front
          ? groups.map((g) => (
              <section className="section" key={g.key} aria-labelledby={`g-${g.key}`}>
                <div className="section-head">
                  <h2 id={`g-${g.key}`}>{g.plural}</h2>
                  {g.all.length > g.items.length && (
                    <Link className="see-all" href={editionHref(basePath, { category: g.key })} rel="nofollow">
                      See all {cats[g.key]} →
                    </Link>
                  )}
                </div>
                <Grid items={g.items} />
              </section>
            ))
          : items.length > 0 && <Grid items={items} />}

        {pages > 1 && (
          <nav className="pager" aria-label="Pages">
            {page > 1 ? <Link className="btn" href={editionHref(basePath, { category, source, page: page - 1 })}>← Previous page</Link> : <span />}
            {page < pages ? <Link className="btn" href={editionHref(basePath, { category, source, page: page + 1 })}>Next page →</Link> : <span />}
          </nav>
        )}

        {run && run.sources.length > 0 && (
          <details className="sources-all">
            <summary>
              Gathered from {sourcesOk} of {run.sources.length} sources · how to read this
            </summary>
            <p>
              Headlines link to the original source. <b>Confirmed</b> means the company said it, <b>reported</b> means a
              publication did, and <b>unverified</b> marks a claim nobody independent has checked.{' '}
              <Link href="/about">How this feed is made</Link>
            </p>
            <ul>
              {run.sources.map((s) => (
                <li key={s.source}>
                  {s.ok && (s.kept ?? 0) > 0 ? (
                    <Link href={editionHref(basePath, { source: s.source })} rel="nofollow">
                      {s.name ?? s.source}
                    </Link>
                  ) : (
                    <span>{s.name ?? s.source}</span>
                  )}
                  <span className={s.ok ? undefined : 'src-fail'}>{s.ok ? `${s.kept ?? 0}` : 'unavailable'}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </main>
    </>
  );
}
