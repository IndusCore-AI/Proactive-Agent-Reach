import type { Metadata } from 'next';
import Link from 'next/link';

import { Bar, HomeLink } from '@/components/Chrome';
import { DeskUpdates } from '@/components/Desk';
import { LocalTime } from '@/components/LocalTime';
import { FoundersBar } from '@/components/Movers';
import { getDeskUpdates, getMoverUpdates } from '@/lib/api';
import { currentFounder } from '@/lib/founders';
import { abs, moverPath } from '@/lib/format';
import type { MoverUpdate } from '@/lib/types';

// What changed on Movers to watch. Everyone sees movers added and new stories;
// an unlocked browser also sees proposals, votes, stages and scores, with who
// did what. Per request, never cached for founders.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Movers: updates',
  description: 'What changed on Movers to watch: companies, apps and skills added, and new stories about them.',
  alternates: { canonical: abs('/movers/updates') },
  robots: { index: false, follow: true },
};

function line(u: MoverUpdate): string {
  return u.kind === 'added'
    ? 'added to the list'
    : `${u.count ?? 'new'} new ${u.count === 1 ? 'story' : 'stories'}`;
}

export default async function Updates() {
  const me = await currentFounder();
  const desk = me ? await getDeskUpdates() : null;
  const pub = desk ? null : await getMoverUpdates();

  return (
    <>
      <Bar current="movers" />
      <div className="wrap">
        <ol className="crumbs">
          <li>
            <HomeLink>Today</HomeLink>
          </li>
          <li>
            <Link href="/movers">Movers to watch</Link>
          </li>
          <li aria-current="page">Updates</li>
        </ol>
        <header className="masthead compact movers-head">
          <div>
            <h1 className="page-title">Updates</h1>
            <p className="tagline">
              {desk ? 'Everything that changed on the desk, newest first, with who did it.' : 'Movers added to the list and new stories about them, newest first.'}
            </p>
          </div>
          {me && <FoundersBar who={me} />}
        </header>
        <main id="main" className="front">
          {me && !desk && <p className="notice">Couldn&apos;t load the desk log just now, so this is the public list. Reload to try again.</p>}
          {desk ? (
            desk.updates.length ? <DeskUpdates updates={desk.updates} /> : <p className="empty">Nothing has changed yet.</p>
          ) : pub && pub.updates.length ? (
            <ol className="updates">
              {pub.updates.map((u) => (
                <li key={u.id}>
                  <LocalTime ts={u.at} />
                  <span>
                    <Link href={u.kind === 'news' ? `${moverPath(u.mover_id)}#news` : moverPath(u.mover_id)}>{u.name}</Link> {line(u)}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="empty">Nothing has changed yet.</p>
          )}
        </main>
      </div>
    </>
  );
}
