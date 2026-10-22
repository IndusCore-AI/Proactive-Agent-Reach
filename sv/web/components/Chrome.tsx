import Link from 'next/link';

import { SITE_NAME } from '@/lib/format';

// The bare /sv is the one path induscore.site cannot proxy for a client-side
// (RSC) navigation, so links to it are plain anchors: always a full page load.
export function HomeLink(props: Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'>) {
  return <a href="/sv" {...props} />;
}

const NAV = [
  { href: '/', label: 'Today', key: 'today' },
  { href: '/archive', label: 'Archive', key: 'archive' },
  { href: '/topics', label: 'Topics', key: 'topics' },
  { href: '/search', label: 'Search', key: 'search' },
  { href: '/about', label: 'About', key: 'about' },
];

export function Bar({ current }: { current?: string }) {
  return (
    <header className="bar">
      <div className="wrap bar-inner">
        <HomeLink className="wordmark" aria-label={`${SITE_NAME}, today's edition`}>
          <span className="mark" aria-hidden="true">SV</span>
          <span className="long">{SITE_NAME}</span>
          <span className="short">Keeping Up</span>
        </HomeLink>
        <nav className="nav" aria-label="Sections">
          {NAV.map((n) =>
            n.href === '/' ? (
              <HomeLink key={n.key} aria-current={current === n.key ? 'page' : undefined}>
                {n.label}
              </HomeLink>
            ) : (
              <Link key={n.key} href={n.href} aria-current={current === n.key ? 'page' : undefined}>
                {n.label}
              </Link>
            ),
          )}
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="foot">
      <div className="wrap">
        <nav aria-label="Footer">
          <HomeLink>Today</HomeLink>
          <Link href="/archive">Archive</Link>
          <Link href="/topics">Topics</Link>
          <Link href="/about">How this feed is made</Link>
          <a href="/sv/feed.xml">RSS</a>
          <a href="https://induscore.site">IndusCore</a>
        </nav>
        <p>
          Every story links to its original source. We store titles, dates and short source excerpts only, never the
          articles or their media. Funding figures are shown as the source states them.
        </p>
        <p>Compiled daily with Claude Code by the IndusCore team. Times are Pacific.</p>
      </div>
    </footer>
  );
}

export function JsonLd({ data }: { data: unknown }) {
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, '\\u003c') }} />;
}
