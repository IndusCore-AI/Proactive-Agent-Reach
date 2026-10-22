import Link from 'next/link';

import { Bar } from '@/components/Chrome';

export default function NotFound() {
  return (
    <>
      <Bar />
      <div className="wrap">
        <main id="main" className="empty">
          <h1 className="page-title">Not here</h1>
          <p>That page doesn’t exist. Editions live at dates like /sv/2026-10-22, and only for days up to today.</p>
          <p>
            <Link href="/">Today’s edition</Link> · <Link href="/archive">Archive</Link>
          </p>
        </main>
      </div>
    </>
  );
}
