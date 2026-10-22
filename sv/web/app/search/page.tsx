import type { Metadata } from 'next';

import { Bar } from '@/components/Chrome';
import { Card } from '@/components/Cards';
import { search } from '@/lib/api';

type SP = Promise<Record<string, string | string[] | undefined>>;

export const metadata: Metadata = {
  title: 'Search',
  robots: { index: false, follow: true },
};

export default async function Search({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const raw = Array.isArray(sp.q) ? sp.q[0] : sp.q;
  const q = (raw ?? '').trim().slice(0, 100);
  const results = q.length >= 2 ? await search(q) : null;
  return (
    <>
      <Bar current="search" />
      <div className="wrap">
        <header className="masthead">
          <h1 className="page-title">Search</h1>
          <form className="search" action="/sv/search" method="get" role="search">
            <label htmlFor="q" className="sr-only">
              Search stories
            </label>
            <input id="q" name="q" type="search" defaultValue={q} placeholder="Companies, investors, technologies…" minLength={2} maxLength={100} />
            <button className="btn primary" type="submit">
              Search
            </button>
          </form>
        </header>
        <main id="main" style={{ paddingBottom: 56 }}>
          {results && (
            <p className="edition-meta" style={{ marginTop: 16 }} role="status">
              {results.total} {results.total === 1 ? 'result' : 'results'} for “{q}”
            </p>
          )}
          {results && results.total === 0 && <p className="empty">Nothing in the archive matches. Try a company name or a broader word.</p>}
          {results && results.items.length > 0 && (
            <div className="grid">
              {results.items.map((it) => (
                <Card key={it.id} item={it} showEdition />
              ))}
            </div>
          )}
        </main>
      </div>
    </>
  );
}
