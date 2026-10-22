import type { Metadata } from 'next';
import Link from 'next/link';

import { Bar } from '@/components/Chrome';
import { LockButton } from '@/components/Movers';
import { isUnlocked } from '@/lib/founders';

// Bookmarked by the founders; linked from nowhere, never indexed.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Founders',
  robots: { index: false, follow: false, nocache: true },
};

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Unlock({ searchParams }: { searchParams: SP }) {
  const failed = (await searchParams).failed !== undefined;
  const unlocked = await isUnlocked();
  return (
    <>
      <Bar current="movers" />
      <div className="wrap">
        <main id="main" className="unlock">
          <h1 className="page-title">Founders</h1>
          {unlocked ? (
            <>
              <p className="tagline">This browser is unlocked for 30 days.</p>
              <div className="cta">
                <Link className="btn primary" href="/movers">
                  Go to Movers
                </Link>
                <LockButton />
              </div>
            </>
          ) : (
            <form className="unlock-form" action="/sv/api/founders/unlock" method="post">
              <label htmlFor="passphrase">Passphrase</label>
              <div className="search">
                <input
                  id="passphrase"
                  name="passphrase"
                  type="password"
                  autoComplete="current-password"
                  required
                  maxLength={512}
                  aria-invalid={failed || undefined}
                  aria-describedby={failed ? 'unlock-error' : undefined}
                  autoFocus
                />
                <button className="btn primary" type="submit">
                  Unlock
                </button>
              </div>
              {failed && (
                <p id="unlock-error" className="unlock-error" role="alert">
                  That passphrase didn&apos;t match.
                </p>
              )}
            </form>
          )}
        </main>
      </div>
    </>
  );
}
