import type { Metadata } from 'next';
import Link from 'next/link';

import { Bar } from '@/components/Chrome';
import { DatePicker } from '@/components/Edition';
import { getDates } from '@/lib/api';
import { SITE_NAME, abs } from '@/lib/format';

// Rendered per request from the data cache (5 min, cleared on ingest), so a
// build never depends on the VM being reachable.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Archive of daily editions',
  description: `Every daily edition of ${SITE_NAME}: startup funding, launches, founder discussions and VC news, by date.`,
  alternates: { canonical: abs('/archive') },
};

export default async function Archive() {
  const { dates } = await getDates();
  const months = new Map<string, typeof dates>();
  for (const d of dates) {
    const key = d.date.slice(0, 7);
    months.set(key, [...(months.get(key) ?? []), d]);
  }
  const monthName = (ym: string) =>
    new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'long', year: 'numeric' }).format(new Date(`${ym}-15T12:00:00Z`));
  const day = (iso: string) =>
    new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric' }).format(new Date(`${iso}T12:00:00Z`));
  return (
    <>
      <Bar current="archive" />
      <div className="wrap">
        <header className="masthead">
          <h1 className="page-title">Archive</h1>
          <p className="tagline">Each edition keeps the stories it carried that day, so a link to a date stays the same page.</p>
          <div style={{ marginTop: 16 }}>
            <DatePicker />
          </div>
        </header>
        <main id="main" style={{ paddingBottom: 56 }}>
          {dates.length === 0 && <p className="empty">No editions yet.</p>}
          {[...months.entries()].map(([ym, ds]) => (
            <section className="archive-month" key={ym}>
              <h2>{monthName(ym)}</h2>
              <ul className="days">
                {ds.map((d) => (
                  <li key={d.date}>
                    <Link href={`/${d.date}`}>
                      {day(d.date)}
                      <small>
                        {d.count} {d.count === 1 ? 'story' : 'stories'}
                      </small>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </main>
      </div>
    </>
  );
}
