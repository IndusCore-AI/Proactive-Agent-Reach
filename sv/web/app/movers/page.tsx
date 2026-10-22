import type { Metadata } from 'next';
import Link from 'next/link';

import { Bar, JsonLd } from '@/components/Chrome';
import { DeskStrip, QueueRow, STAGES } from '@/components/Desk';
import { FoundersBar, MoverCard } from '@/components/Movers';
import { getDesk, getMovers, type DeskQuery } from '@/lib/api';
import { currentFounder } from '@/lib/founders';
import { MOVER_KINDS, SITE_NAME, abs, moverKind, moverPath } from '@/lib/format';
import type { DeskList, MoverKind, MoverStage, MoverStatus } from '@/lib/types';
import type { FounderKey } from '@/lib/unlock';

// Per request: public facts come from the data cache (5 min, cleared on
// ingest); the founders' desk only for an unlocked browser, never cached.
export const dynamic = 'force-dynamic';

type SP = Record<string, string | string[] | undefined>;

const PAGE_SIZE = 60;
const TITLE = 'Movers to watch';
const INTRO = 'Companies, apps and skills gaining traction. Every figure links to its source and the date it was true.';

const PUBLIC_SORTS = [
  { key: 'trending', label: 'Trending', hint: 'Most stories in the last 14 days' },
  { key: 'newest', label: 'Newest', hint: 'Most recently added' },
] as const;
const DESK_SORTS = [
  { key: 'fit', label: 'Fit for us' },
  { key: 'votes', label: 'Votes' },
  { key: 'trending', label: 'Trending' },
  { key: 'newest', label: 'Newest' },
] as const;

function one(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

function pick<T extends string>(v: string | string[] | undefined, allowed: readonly { key: T }[]): T | undefined {
  const s = one(v);
  return allowed.some((a) => a.key === s) ? (s as T) : undefined;
}

function pageOf(sp: SP): number {
  const p = Number(one(sp.page) ?? '1');
  return Number.isInteger(p) && p >= 1 && p <= 50 ? p : 1;
}

/** A /movers URL with these filters; undefined values drop out. */
function href(q: Record<string, string | number | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== '' && !(k === 'page' && v === 1)) p.set(k, String(v));
  const s = p.toString();
  return `/movers${s ? `?${s}` : ''}`;
}

export async function generateMetadata({ searchParams }: { searchParams: Promise<SP> }): Promise<Metadata> {
  const sp = await searchParams;
  const filtered = Object.keys(sp).length > 0;
  return {
    title: TITLE,
    description: `${INTRO} From ${SITE_NAME}.`,
    alternates: { canonical: abs('/movers') },
    openGraph: { title: TITLE, description: INTRO, url: abs('/movers') },
    // Filtered and sorted views are for people; the plain list is the one to
    // index (and keeps the layout's robots defaults, so the key is left out).
    ...(filtered ? { robots: { index: false, follow: true } } : {}),
  };
}

export default async function Movers({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const me = await currentFounder();
  if (me) {
    const desk = await DeskView({ sp, me });
    if (desk) return desk;
  }
  return <PublicView sp={sp} unlocked={me !== null} />;
}

async function PublicView({ sp, unlocked }: { sp: SP; unlocked: boolean }) {
  const kind = moverKind(sp.kind);
  const sort = pick(sp.sort, PUBLIC_SORTS) ?? 'trending';
  const page = pageOf(sp);
  const data = await getMovers({ kind, sort, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
  const kinds = data.facets.kinds ?? {};
  const all = Object.values(kinds).reduce((a, b) => a + (b ?? 0), 0);
  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const label = kind ? MOVER_KINDS.find((k) => k.key === kind)!.plural.toLowerCase() : 'movers';
  const keep = { kind, sort: sort === 'trending' ? undefined : sort };

  return (
    <>
      <Bar current="movers" />
      {!kind && page === 1 && sort === 'trending' && (
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
          {unlocked && (
            <p className="notice">Couldn&apos;t load the founders&apos; desk just now, so this is the public list. Reload to try again.</p>
          )}
          <div className="filters">
            <ul className="chips" aria-label="Filter by kind">
              <li>
                <Link className="chip" href={href({ ...keep, kind: undefined })} aria-current={!kind ? 'true' : undefined}>
                  All <span className="n">{all}</span>
                </Link>
              </li>
              {MOVER_KINDS.map((k) => (
                <li key={k.key}>
                  <Link className="chip" href={href({ ...keep, kind: k.key })} aria-current={kind === k.key ? 'true' : undefined} rel="nofollow">
                    {k.plural} <span className="n">{kinds[k.key] ?? 0}</span>
                  </Link>
                </li>
              ))}
            </ul>
            <ul className="chips sort" aria-label="Sort">
              {PUBLIC_SORTS.map((s) => (
                <li key={s.key}>
                  <Link
                    className="chip"
                    href={href({ ...keep, sort: s.key === 'trending' ? undefined : s.key })}
                    aria-current={sort === s.key ? 'true' : undefined}
                    title={s.hint}
                    rel="nofollow"
                  >
                    {s.label}
                  </Link>
                </li>
              ))}
              <li>
                <Link className="chip quiet" href="/movers/updates">
                  Updates
                </Link>
              </li>
            </ul>
          </div>
          {data.movers.length === 0 ? (
            <p className="empty">No {label} on the list yet.</p>
          ) : (
            <div className="movers">
              {data.movers.map((m) => (
                <MoverCard key={m.id} mover={m} />
              ))}
            </div>
          )}
          {pages > 1 && (
            <nav className="pager" aria-label="Pages">
              {page > 1 ? <Link className="btn" href={href({ ...keep, page: page - 1 })}>← Previous page</Link> : <span />}
              {page < pages ? <Link className="btn" href={href({ ...keep, page: page + 1 })}>Next page →</Link> : <span />}
            </nav>
          )}
        </main>
      </div>
    </>
  );
}

const STATUS_VIEWS: { key: MoverStatus | 'active'; label: string }[] = [
  { key: 'watching', label: 'On the list' },
  { key: 'active', label: 'Everything open' },
  { key: 'archived', label: 'Archived' },
];

/** The founders' desk: the queue waiting for a decision, then everything
 * else with our score, stage and votes. null when the desk cannot load (the
 * page then falls back to the public list with a notice). */
async function DeskView({ sp, me }: { sp: SP; me: FounderKey }) {
  const kind = moverKind(sp.kind) as MoverKind | undefined;
  const stage = pick(sp.stage, STAGES) as MoverStage | undefined;
  const status = pick(sp.status, STATUS_VIEWS) ?? 'watching';
  const sort = pick(sp.sort, DESK_SORTS) ?? 'fit';
  const q: DeskQuery = { kind, stage, sort, status };
  const [queue, list] = await Promise.all([getDesk({ status: 'proposed', sort: 'fit' }), getDesk(q)]);
  if (!queue || !list) return null;

  const keep = { kind, stage, sort: sort === 'fit' ? undefined : sort, status: status === 'watching' ? undefined : status };
  const back = href(keep);
  const waitingOnMe = queue.movers.filter((m) => !m.votes.some((v) => v.voter === me)).length;
  const facets: DeskList['facets'] = list.facets;
  const stat = (n: number | undefined) => n ?? 0;

  return (
    <>
      <Bar current="movers" />
      <div className="wrap">
        <header className="masthead movers-head">
          <div>
            <p className="kicker">Founders&apos; desk</p>
            <h1 className="page-title">{TITLE}</h1>
            <p className="tagline">What to look at, what it would take, and what we decided. Our take, scores and votes never leave this view.</p>
          </div>
          <FoundersBar who={me} />
        </header>
        <main id="main" className="front desk">
          <ul className="desk-stats" aria-label="At a glance">
            <li>
              <a href="#queue">
                <strong>{queue.movers.length}</strong>
                <span>Waiting for a decision{waitingOnMe ? `, ${waitingOnMe} without your vote` : ''}</span>
              </a>
            </li>
            <li>
              <Link href={href({ ...keep, stage: 'researching', status: 'active' })}>
                <strong>{stat(facets.stage_active.researching)}</strong>
                <span>Researching</span>
              </Link>
            </li>
            <li>
              <Link href={href({ ...keep, stage: 'building', status: 'active' })}>
                <strong>{stat(facets.stage_active.building)}</strong>
                <span>Building</span>
              </Link>
            </li>
            <li>
              <Link href={href({})}>
                <strong>{stat(facets.status.watching)}</strong>
                <span>On the public list</span>
              </Link>
            </li>
          </ul>

          <section className="section" id="queue" aria-labelledby="queue-head">
            <div className="section-head">
              <h2 id="queue-head">Waiting for a decision</h2>
              <span>Proposed by a run or a founder. Best fit first. Nobody else sees these.</span>
            </div>
            {queue.movers.length ? (
              <ul className="queue">
                {queue.movers.map((m) => (
                  <QueueRow key={m.id} mover={m} me={me} back={back} />
                ))}
              </ul>
            ) : (
              <p className="empty">Nothing waiting. New finds land here for a yes or no.</p>
            )}
          </section>

          <section className="section" aria-labelledby="list-head">
            <div className="section-head">
              <h2 id="list-head">{STATUS_VIEWS.find((v) => v.key === status)!.label}</h2>
              <Link className="more-link" href="/movers/updates">
                Updates
              </Link>
            </div>
            <div className="filters">
              <ul className="chips" aria-label="Sort">
                {DESK_SORTS.map((s) => (
                  <li key={s.key}>
                    <Link className="chip" href={href({ ...keep, sort: s.key === 'fit' ? undefined : s.key })} aria-current={sort === s.key ? 'true' : undefined}>
                      {s.label}
                    </Link>
                  </li>
                ))}
              </ul>
              <ul className="chips" aria-label="Filter by kind">
                <li>
                  <Link className="chip" href={href({ ...keep, kind: undefined })} aria-current={!kind ? 'true' : undefined}>
                    All kinds
                  </Link>
                </li>
                {MOVER_KINDS.map((k) => (
                  <li key={k.key}>
                    <Link className="chip" href={href({ ...keep, kind: k.key })} aria-current={kind === k.key ? 'true' : undefined}>
                      {k.plural} <span className="n">{stat(facets.kind[k.key])}</span>
                    </Link>
                  </li>
                ))}
              </ul>
              <ul className="chips" aria-label="Filter by stage">
                <li>
                  <Link className="chip" href={href({ ...keep, stage: undefined })} aria-current={!stage ? 'true' : undefined}>
                    Any stage
                  </Link>
                </li>
                {STAGES.map((s) => (
                  <li key={s.key}>
                    <Link className="chip" href={href({ ...keep, stage: s.key })} aria-current={stage === s.key ? 'true' : undefined}>
                      {s.label} <span className="n">{stat(facets.stage[s.key])}</span>
                    </Link>
                  </li>
                ))}
              </ul>
              <ul className="chips" aria-label="Show">
                {STATUS_VIEWS.map((v) => (
                  <li key={v.key}>
                    <Link
                      className={`chip${v.key === 'archived' ? ' quiet' : ''}`}
                      href={href({ ...keep, status: v.key === 'watching' ? undefined : v.key })}
                      aria-current={status === v.key ? 'true' : undefined}
                    >
                      {v.label}{' '}
                      <span className="n">
                        {v.key === 'active' ? stat(facets.status.proposed) + stat(facets.status.watching) : stat(facets.status[v.key])}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
            {list.movers.length === 0 ? (
              <p className="empty">Nothing matches these filters.</p>
            ) : (
              <div className="movers">
                {list.movers.map((m) => (
                  <MoverCard key={m.id} mover={m} take={{ notes: m.notes, failed: false }} strip={<DeskStrip mover={m} />} />
                ))}
              </div>
            )}
          </section>
        </main>
      </div>
    </>
  );
}
