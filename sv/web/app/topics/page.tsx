import type { Metadata } from 'next';
import Link from 'next/link';

import { Bar } from '@/components/Chrome';
import { getTopics } from '@/lib/api';
import { SITE_NAME, abs, tagLabel } from '@/lib/format';

// Rendered per request from the data cache (5 min, cleared on ingest), so a
// build never depends on the VM being reachable.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Topics',
  description: `Startup stories by topic on ${SITE_NAME}: AI, developer tools, infrastructure, fintech, robotics, funding and more.`,
  alternates: { canonical: abs('/topics') },
};

export default async function Topics() {
  const { topics } = await getTopics();
  return (
    <>
      <Bar current="topics" />
      <div className="wrap">
        <header className="masthead">
          <h1 className="page-title">Topics</h1>
          <p className="tagline">Every story is tagged with what it is about. A topic page collects them across editions.</p>
        </header>
        <main id="main" style={{ paddingBottom: 56 }}>
          {topics.length === 0 ? (
            <p className="empty">No topics yet.</p>
          ) : (
            <ul className="topic-cloud">
              {topics.map((t) => (
                <li key={t.tag}>
                  <Link className="chip" href={`/topics/${t.tag}`}>
                    {tagLabel(t.tag)} <span className="n">{t.count}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </main>
      </div>
    </>
  );
}
