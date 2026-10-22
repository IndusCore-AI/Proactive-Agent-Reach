import type { Metadata, Viewport } from 'next';
import { Analytics } from '@vercel/analytics/next';

import { Footer } from '@/components/Chrome';
import { SITE_NAME, SITE_ORIGIN, TAGLINE, abs } from '@/lib/format';

import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(SITE_ORIGIN),
  title: { default: `${SITE_NAME}: startup funding, launches and founder news, daily`, template: `%s · ${SITE_NAME}` },
  description: TAGLINE,
  applicationName: SITE_NAME,
  alternates: { canonical: abs('/'), types: { 'application/rss+xml': abs('/feed.xml') } },
  openGraph: { type: 'website', siteName: SITE_NAME, url: abs('/'), images: [{ url: '/sv/opengraph-image', width: 1200, height: 630 }] },
  twitter: { card: 'summary_large_image' },
  robots: { index: true, follow: true, 'max-snippet': -1, 'max-image-preview': 'large' },
  icons: { icon: '/sv/icon.svg' },
};

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#fbfaf7' },
    { media: '(prefers-color-scheme: dark)', color: '#0f1012' },
  ],
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">
          Skip to stories
        </a>
        {children}
        <Footer />
        <Analytics />
      </body>
    </html>
  );
}
