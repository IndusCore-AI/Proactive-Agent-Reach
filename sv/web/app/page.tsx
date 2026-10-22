import type { Metadata } from 'next';

import { Bar } from '@/components/Chrome';
import { EditionView, PAGE_SIZE } from '@/components/Edition';
import { getFeed } from '@/lib/api';
import { SITE_NAME, TAGLINE, abs, longDate, todayPT } from '@/lib/format';
import { hasFilters, readFilters } from '@/lib/params';

type SP = Promise<Record<string, string | string[] | undefined>>;

export async function generateMetadata({ searchParams }: { searchParams: SP }): Promise<Metadata> {
  const sp = await searchParams;
  return {
    title: { absolute: `${SITE_NAME}: startup funding, launches and founder news, daily` },
    description: TAGLINE,
    alternates: { canonical: abs('/') },
    openGraph: { title: SITE_NAME, description: TAGLINE, url: abs('/') },
    // Filtered views are for people; the unfiltered page is the one to index.
    robots: hasFilters(sp) ? { index: false, follow: true } : undefined,
  };
}

export default async function Today({ searchParams }: { searchParams: SP }) {
  const { category, source, page } = readFilters(await searchParams);
  const today = todayPT();
  const query = { category, source, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE };
  let feed = await getFeed({ date: today, ...query });
  let basePath = '/';
  let notice: React.ReactNode = null;
  const todayHasEdition = Object.keys(feed.facets.categories ?? {}).length > 0;
  if (!todayHasEdition) {
    const latest = await getFeed(query);
    if (!latest.date) {
      feed = latest; // nothing has ever been ingested
    } else {
      feed = latest;
      basePath = `/${latest.date}`;
      notice = (
        <p className="notice">
          <strong>Today&apos;s edition ({longDate(today)}) hasn&apos;t been compiled yet.</strong> Below is the most
          recent edition, {longDate(latest.date)}. Nothing from today is mixed in.
        </p>
      );
    }
  }
  return (
    <>
      <Bar current="today" />
      <div className="wrap">
        <header className="masthead compact">
          <h1 className="display">{SITE_NAME}</h1>
          <p className="tagline">Startup funding, launches, founders and VCs: the day&apos;s best, from the sources that break it.</p>
        </header>
        {feed.date ? (
          <EditionView feed={feed} basePath={basePath} category={category} source={source} page={page} notice={notice} />
        ) : (
          <main id="main" className="empty">
            <p>The first edition is being compiled. Check back shortly.</p>
          </main>
        )}
      </div>
    </>
  );
}
