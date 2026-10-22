'use client';

import Link from 'next/link';

export default function Error({ reset }: { reset: () => void }) {
  return (
    <div className="wrap">
      <main id="main" className="empty">
        <h1 className="page-title">The feed is briefly unavailable</h1>
        <p>We couldn’t reach the story archive just now. Nothing is lost; it usually comes back within a minute.</p>
        <p>
          <button className="btn" type="button" onClick={reset}>
            Try again
          </button>{' '}
          <Link href="/">Today’s edition</Link>
        </p>
      </main>
    </div>
  );
}
