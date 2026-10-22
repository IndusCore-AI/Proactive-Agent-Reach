import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { Bar } from '@/components/Chrome';
import { StoryCard } from '@/components/StoryCard';
import { getTopic } from '@/lib/api';
import { SITE_NAME, abs, tagLabel } from '@/lib/format';

type Params = Promise<{ tag: string }>;
type SP = Promise<Record<string, string | string[] | undefined>>;

// A topic page is worth indexing only once it holds a handful of stories.
const INDEX_MIN = 3;

function valid(tag: string) {
  return /^[a-z0-9][a-z0-9-]{1,29}$/.test(tag);
}

function pageOf(sp: Record<string, string | string[] | undefined>) {
  const p = Number(Array.isArray(sp.page) ? sp.page[0] : sp.page ?? '1');
  return Number.isInteger(p) && p >= 1 && p <= 100 ? p : 1;
}

export async function generateMetadata({ params, searchParams }: { params: Params; searchParams: SP }): Promise<Metadata> {
  const { tag } = await params;
  if (!valid(tag)) return {};
  const page = pageOf(await searchParams);
  const data = await getTopic(tag);
  const label = tagLabel(tag);
  return {
    title: `${label}: startup news and launches`,
    description: `${data.total} ${label} stories tracked by ${SITE_NAME}, newest first, each linked to its original source.`,
    alternates: { canonical: abs(`/topics/${tag}${page > 1 ? `?page=${page}` : ''}`) },
    robots: data.total < INDEX_MIN ? { index: false, follow: true } : undefined,
  };
}

export default async function Topic({ params, searchParams }: { params: Params; searchParams: SP }) {
  const { tag } = await params;
  if (!valid(tag)) notFound();
  const page = pageOf(await searchParams);
  const data = await getTopic(tag, (page - 1) * 40);
  if (data.total === 0) notFound();
  const pages = Math.ceil(data.total / 40);
  return (
    <>
      <Bar current="topics" />
      <div className="wrap">
        <header className="masthead">
          <p className="kicker">
            <Link href="/topics">Topics</Link>
          </p>
          <h1 className="page-title">{tagLabel(tag)}</h1>
          <p className="tagline">
            {data.total} {data.total === 1 ? 'story' : 'stories'} across editions, newest first.
          </p>
        </header>
        <main id="main" style={{ maxWidth: 820, paddingBottom: 56 }}>
          <ul className="stories">
            {data.items.map((it) => (
              <StoryCard key={it.id} item={it} showEdition />
            ))}
          </ul>
          {pages > 1 && (
            <nav className="pager" aria-label="Pages">
              {page > 1 ? <Link className="btn" href={`/topics/${tag}${page > 2 ? `?page=${page - 1}` : ''}`}>← Newer</Link> : <span />}
              {page < pages ? <Link className="btn" href={`/topics/${tag}?page=${page + 1}`}>Older →</Link> : <span />}
            </nav>
          )}
        </main>
      </div>
    </>
  );
}
