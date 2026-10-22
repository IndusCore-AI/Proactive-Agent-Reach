import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { Bar } from '@/components/Chrome';
import { DatePicker, EditionView, PAGE_SIZE } from '@/components/Edition';
import { getFeed } from '@/lib/api';
import { FIRST_EDITION, SITE_NAME, abs, isIsoDate, longDate, shortDate, todayPT } from '@/lib/format';
import { hasFilters, readFilters } from '@/lib/params';

type Params = Promise<{ date: string }>;
type SP = Promise<Record<string, string | string[] | undefined>>;

function validDate(date: string): boolean {
  return isIsoDate(date) && date >= FIRST_EDITION && date <= todayPT();
}

export async function generateMetadata({ params, searchParams }: { params: Params; searchParams: SP }): Promise<Metadata> {
  const { date } = await params;
  if (!validDate(date)) return {};
  const sp = await searchParams;
  const feed = await getFeed({ date, limit: 3 });
  const empty = Object.keys(feed.facets.categories ?? {}).length === 0;
  const n = Object.values(feed.facets.categories ?? {}).reduce((a, b) => a + (b ?? 0), 0);
  const title = `Startup news, funding and launches for ${longDate(date)}`;
  const description = empty
    ? `No edition of ${SITE_NAME} was compiled for ${longDate(date)}.`
    : `${n} startup and technology stories from ${shortDate(date)}: ${feed.items.map((i) => i.title).join('; ')}.`.slice(0, 300);
  return {
    title,
    description,
    alternates: { canonical: abs(`/${date}`) },
    openGraph: { title: `${SITE_NAME}: ${longDate(date)}`, description, url: abs(`/${date}`), type: 'website' },
    robots: empty || hasFilters(sp) ? { index: false, follow: true } : undefined,
  };
}

export default async function EditionPage({ params, searchParams }: { params: Params; searchParams: SP }) {
  const { date } = await params;
  if (!validDate(date)) notFound();
  const { category, source, page } = readFilters(await searchParams);
  const feed = await getFeed({ date, category, source, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
  const empty = Object.keys(feed.facets.categories ?? {}).length === 0;
  return (
    <>
      <Bar current="archive" />
      <div className="wrap">
        <header className="masthead">
          <p className="kicker">
            <Link href="/archive">Archive</Link> · Edition
          </p>
          <h1 className="page-title">{longDate(date)}</h1>
        </header>
        {empty ? (
          <main id="main" className="empty">
            <p>
              <strong>No edition was compiled for {longDate(date)}.</strong>{' '}
              {date === todayPT() ? 'Today’s run hasn’t happened yet.' : 'The feed skipped this day or it predates the archive.'}
            </p>
            <p>
              {feed.prev && <Link href={`/${feed.prev}`}>← Previous edition: {longDate(feed.prev)}</Link>}
              {feed.prev && feed.next && <br />}
              {feed.next && <Link href={`/${feed.next}`}>Next edition: {longDate(feed.next)} →</Link>}
            </p>
            <DatePicker value={date} />
          </main>
        ) : (
          <EditionView feed={feed} basePath={`/${date}`} category={category} source={source} page={page} />
        )}
      </div>
    </>
  );
}
