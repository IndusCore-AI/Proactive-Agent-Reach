import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { Card } from '@/components/Cards';
import { Bar, HomeLink, JsonLd } from '@/components/Chrome';
import { DecisionPanel, History, NextSteps, STATUS_LABEL, ScoreCard } from '@/components/Desk';
import { LocalTime } from '@/components/LocalTime';
import { MoverLogo } from '@/components/MoverLogo';
import { FoundersBar, Markets, OurTake, TractionList } from '@/components/Movers';
import { ApiError, getDeskMover, getMover } from '@/lib/api';
import { currentFounder } from '@/lib/founders';
import { nextSteps } from '@/lib/nextSteps';
import {
  CLAIM_LABEL, MOVER_ID_RE, MOVER_KIND_LABEL, SITE_NAME, abs, hostOf, moverPath, shortDate, tagLabel,
} from '@/lib/format';
import type { DeskDetail, MoverDetail } from '@/lib/types';

// Per request: public facts from the data cache; the founders' desk (take,
// score, votes, stage, next steps, and movers not yet public) only for an
// unlocked browser, never cached.
export const dynamic = 'force-dynamic';

type Params = Promise<{ id: string }>;
type SP = Promise<Record<string, string | string[] | undefined>>;

const CLAIM_EXPLAINED = {
  confirmed: 'The company or maker states these facts itself.',
  reported: 'A publication reported these facts; the company may not have confirmed them.',
  unverified: 'Figures from posts or discussions that nobody independent has checked.',
} as const;

const KIND_PHRASE = { company: 'a company to watch', app: 'an app to watch', skill: 'a skill to watch' } as const;

async function loadPublic(id: string): Promise<MoverDetail> {
  if (!MOVER_ID_RE.test(id)) notFound();
  try {
    return await getMover(id);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 422)) notFound();
    throw err;
  }
}

/** The desk's view for a founder (any status), else the public facts. */
async function load(id: string): Promise<{ m: MoverDetail; desk: DeskDetail | null }> {
  if (!MOVER_ID_RE.test(id)) notFound();
  const desk = (await currentFounder()) ? await getDeskMover(id) : null;
  return desk ? { m: desk, desk } : { m: await loadPublic(id), desk: null };
}

/** Public facts only: the one-liner and the first traction figures. */
function describe(m: MoverDetail): string {
  const figures = m.traction.slice(0, 2).map((t) => `${t.label}: ${t.value} (as of ${shortDate(t.as_of)})`);
  return [m.one_liner, figures.length ? `${figures.join('; ')}.` : null].filter(Boolean).join(' ').slice(0, 300);
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { m, desk } = await load((await params).id);
  const url = abs(moverPath(m.id));
  const title = `${m.name}, ${KIND_PHRASE[m.kind]}`;
  return {
    title,
    // The founders' view of a page is never indexed (a proposed mover has no public page at all).
    ...(desk ? { robots: { index: false, follow: false, nocache: true } } : {}),
    description: describe(m),
    alternates: { canonical: url },
    openGraph: { title, description: describe(m), url, type: 'website' },
    twitter: { title, description: describe(m) },
  };
}

export default async function MoverPage({ params, searchParams }: { params: Params; searchParams: SP }) {
  const { id } = await params;
  const me = await currentFounder();
  const { m, desk } = await load(id);
  const failed = (await searchParams).failed !== undefined;
  const path = moverPath(m.id);

  return (
    <>
      <Bar current="movers" />
      {!desk && <JsonLd
        data={{
          '@context': 'https://schema.org',
          '@graph': [
            {
              '@type': 'WebPage',
              '@id': abs(path),
              url: abs(path),
              name: m.name,
              description: describe(m),
              datePublished: m.first_added_at,
              dateModified: m.updated_at,
              isPartOf: { '@type': 'WebSite', name: SITE_NAME, url: abs('/') },
              keywords: m.tags.map(tagLabel).join(', ') || undefined,
              about: {
                '@type': m.kind === 'company' ? 'Organization' : 'Thing',
                name: m.name,
                url: m.url,
                description: m.one_liner,
              },
            },
            {
              '@type': 'BreadcrumbList',
              itemListElement: [
                { '@type': 'ListItem', position: 1, name: SITE_NAME, item: abs('/') },
                { '@type': 'ListItem', position: 2, name: 'Movers to watch', item: abs('/movers') },
                { '@type': 'ListItem', position: 3, name: m.name, item: abs(path) },
              ],
            },
          ],
        }}
      />}
      <div className="wrap">
        <ol className="crumbs">
          <li>
            <HomeLink>Today</HomeLink>
          </li>
          <li>
            <Link href="/movers">Movers to watch</Link>
          </li>
          <li aria-current="page">{m.name}</li>
        </ol>
        <main id="main" className="detail mover-detail">
          <div className="mover-head">
            <MoverLogo src={m.image_url} kind={m.image_kind} name={m.name} large />
            <div className="mover-name">
              <div className="labels">
                <span className="kind">{MOVER_KIND_LABEL[m.kind]}</span>
                {m.claim_status !== 'confirmed' && <span className="claim">{CLAIM_LABEL[m.claim_status]}</span>}
                {desk && desk.status !== 'watching' && <span className={`status-dot ${desk.status}`}>{STATUS_LABEL[desk.status]}</span>}
              </div>
              <h1 className="story-title">{m.name}</h1>
            </div>
            {me && <FoundersBar who={me} />}
          </div>
          {desk && me && (
            <div className="desk-grid">
              <DecisionPanel mover={desk} me={me} failed={failed} />
              <ScoreCard score={desk.score} />
            </div>
          )}
          <p className="context">{m.one_liner}</p>
          {m.summary && <p className="excerpt">{m.summary}</p>}
          {m.traction.length > 0 && (
            <section aria-labelledby="traction">
              <h2 id="traction" className="sub-head">
                Traction
              </h2>
              <TractionList lines={m.traction} large />
            </section>
          )}
          <Markets markets={m.markets_live} />
          <div className="cta">
            <a className="btn primary" href={m.url} rel="noopener" target="_blank">
              Visit {hostOf(m.url)} ↗
            </a>
          </div>
          {me && <OurTake notes={desk?.notes} failed={!desk} />}
          {desk && <NextSteps steps={nextSteps(desk, abs(path))} />}
          <dl>
            <dt>Kind</dt>
            <dd>{MOVER_KIND_LABEL[m.kind]}</dd>
            <dt>Status</dt>
            <dd>{CLAIM_EXPLAINED[m.claim_status]}</dd>
            <dt>{desk && desk.status === 'proposed' ? 'Proposed' : 'On the list since'}</dt>
            <dd>
              <LocalTime ts={m.first_added_at} style="date" />
            </dd>
            <dt>Facts updated</dt>
            <dd>
              <LocalTime ts={m.updated_at} style="date" />
            </dd>
            {m.tags.length > 0 && (
              <>
                <dt>Topics</dt>
                <dd>{m.tags.map(tagLabel).join(', ')}</dd>
              </>
            )}
          </dl>
          {desk && <History events={desk.events} />}
        </main>
        <section className="section" id="news" aria-labelledby="news-head" style={{ paddingBottom: 48 }}>
          <div className="section-head">
            <h2 id="news-head">Related news</h2>
            {m.news_count > 0 && <span>{m.news_count} {m.news_count === 1 ? 'story' : 'stories'}, newest first</span>}
          </div>
          {m.items.length > 0 ? (
            <div className="grid">
              {m.items.map((it) => (
                <Card key={it.id} item={it} showEdition />
              ))}
            </div>
          ) : (
            <p className="empty">No stories in the feed point here yet.</p>
          )}
        </section>
      </div>
    </>
  );
}
