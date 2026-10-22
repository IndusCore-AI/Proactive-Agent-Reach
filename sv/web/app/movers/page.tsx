import type { Metadata } from 'next';
import Link from 'next/link';

import { Bar, JsonLd } from '@/components/Chrome';
import { FoundersBar, MoverCard } from '@/components/Movers';
import { getMovers, getPrivateNotes } from '@/lib/api';
import { isUnlocked } from '@/lib/founders';
import { MOVER_KINDS, SITE_NAME, abs, moverKind, moverPath } from '@/lib/format';
import type { MoverKind } from '@/lib/types';

// Per request: public facts come from the data cache (5 min, cleared on
// ingest); the founders' take only for an unlocked browser, never cached.
export const dynamic = 'force-dynamic';

type SP = Promise<Record<string, string | string[] | undefined>>;

const PAGE_SIZE = 60;
const TITLE = 'Movers to watch';
const INTRO = 'Companies, apps and skills gaining traction. Every figure links to its source and the date it was true.';

function pageOf(sp: Record<string, string | string[] | undefined>): number {
  const p = Number(Array.isArray(sp.page) ? sp.page[0] : sp.page ?? '1');
  return Number.isInteger(p) && p >= 1 && p <= 50 ? p : 1;
}

function href(kind?: MoverKind, page = 1): string {
  const p = new URLSearchParams();
  if (kind) p.set('kind', kind);
  if (page > 1) p.set('page', String(page));
  const s = p.toString();
  return `/movers${s ? `?${s}` : ''}`;
}

export async function generateMetadata({ searchParams }: { searchParams: SP }): Promise<Metadata> {
  const sp = await searchParams;
  return {
    title: TITLE,
    description: `${INTRO} From ${SITE_NAME}.`,
    alternates: { canonical: abs('/movers') },
    openGraph: { title: TITLE, description: INTRO, url: abs('/movers') },
    // Filtered views are for people; the unfiltered list is the one to index.
    robots: sp.kind !== undefined || sp.page !== undefined ? { index: false, follow: true } : undefined,
  };
}

export default async function Movers({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const kind = moverKind(sp.kind);
  const page = pageOf(sp);
  const unlocked = await isUnlocked();
  const data = await getMovers({ kind, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
  const notes = unlocked ? await getPrivateNotes(data.movers.map((m) => m.id)) : null;
  const kinds = data.facets.kinds ?? {};
  const all = Object.values(kinds).reduce((a, b) => a + (b ?? 0), 0);
  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const label = kind ? MOVER_KINDS.find((k) => k.key === kind)!.plural.toLowerCase() : 'movers';

  return (
    <>
      <Bar current="movers" />
      {!kind && page === 1 && (
        <JsonLd
          data={{
            '@context': 'https://schema.org',
            '@type': 'CollectionPage',
            name: TITLE,
            description: INTRO,
            url: abs('/movers'),
            isPartOf: { '@type': 'WebSite', name: SITE_NAME, url: abs('/') },
            publisher: { '@type': 'Organization', name: 'IndusCore', url: 'https://induscore.site' },
            mainEntity: {
              '@type': 'ItemList',
              numberOfItems: data.total,
              itemListElement: data.movers.map((m, i) => ({ '@type': 'ListItem', position: i + 1, url: abs(moverPath(m.id)), name: m.name })),
            },
          }}
        />
      )}
      <div className="wrap">
        <header className="masthead movers-head">
          <div>
            <h1 className="page-title">{TITLE}</h1>
            <p className="tagline">{INTRO}</p>
          </div>
          {unlocked && <FoundersBar />}
        </header>
        <main id="main" className="front">
          <ul className="chips" aria-label="Filter by kind">
            <li>
              <Link className="chip" href={href()} aria-current={!kind ? 'true' : undefined}>
                All <span className="n">{all}</span>
              </Link>
            </li>
            {MOVER_KINDS.map((k) => (
              <li key={k.key}>
                <Link className="chip" href={href(k.key)} aria-current={kind === k.key ? 'true' : undefined} rel="nofollow">
                  {k.plural} <span className="n">{kinds[k.key] ?? 0}</span>
                </Link>
              </li>
            ))}
          </ul>
          {data.movers.length === 0 ? (
            <p className="empty">No {label} on the list yet.</p>
          ) : (
            <div className="movers">
              {data.movers.map((m) => (
                <MoverCard key={m.id} mover={m} take={unlocked ? { notes: notes?.[m.id], failed: notes === null } : undefined} />
              ))}
            </div>
          )}
          {pages > 1 && (
            <nav className="pager" aria-label="Pages">
              {page > 1 ? <Link className="btn" href={href(kind, page - 1)}>← Previous page</Link> : <span />}
              {page < pages ? <Link className="btn" href={href(kind, page + 1)}>Next page →</Link> : <span />}
            </nav>
          )}
        </main>
      </div>
    </>
  );
}
