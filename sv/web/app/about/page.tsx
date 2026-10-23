import type { Metadata } from 'next';
import Link from 'next/link';

import { Bar, HomeLink, JsonLd } from '@/components/Chrome';
import { SITE_NAME, abs } from '@/lib/format';

// Static pages are cached by induscore.site's edge too (it proxies /sv), so
// give this one a short lifetime: an edit shows up within ten minutes.
export const revalidate = 600;

export const metadata: Metadata = {
  title: 'How this feed is made',
  description: `How ${SITE_NAME} finds, checks, ranks and archives startup news every day, and what it never does.`,
  alternates: { canonical: abs('/about') },
};

const SOURCES: [string, string, string][] = [
  ['Hacker News', 'Front page, Show HN and Launch HN through the public Algolia API', 'Points and comment counts as shown at collection time'],
  ['Y Combinator Launches', 'Company launches posted on ycombinator.com/launches', 'Batch, company and launch votes'],
  ['Product Hunt', 'The public launch feed', 'Product pages are linked, not embedded'],
  ['Startup and technology press', 'TechCrunch (startups, venture, AI), Crunchbase News, Techmeme, GeekWire, SiliconANGLE, The Verge, StrictlyVC and others, through their RSS feeds', 'Headline, date and the feed’s own short description'],
  ['Investors and operators', 'Sequoia, a16z, Lenny’s Newsletter, Not Boring, Tomasz Tunguz, Latent Space', 'Theses and analysis are labelled Analysis or Opinion. Some newsletters (Stratechery, SemiAnalysis, SaaStr) refuse automated readers, so we leave them out'],
  ['Founder and operator essays', 'Sam Altman, Simon Willison, Elad Gil, Benedict Evans, Andrej Karpathy, Dwarkesh Patel, Andrew Chen, and from China and India Interconnected, ChinAI and Sajith Pai, through their feeds', 'Labelled Opinion. Sites without a feed, or that refuse automated readers, are left out'],
  ['YouTube', 'New videos from Y Combinator, a16z, Lenny’s Podcast, Greg Isenberg, Starter Story, My First Million, All-In, Latent Space, Every, 硅谷101 and Think School, through each channel’s public feed', 'Played with YouTube’s own player, loaded only when you press play. View counts as shown at collection time'],
  ['Company and lab announcements', 'OpenAI, Google AI, Hugging Face, GitHub and Stripe blogs', 'Labelled Confirmed when the company is announcing its own news'],
  ['Reddit', 'The day’s top posts in eleven startup, SaaS, AI and Indian startup communities, such as r/startups, r/SaaS, r/SideProject, r/LocalLLaMA and r/StartUpIndia, through public RSS', 'Best effort: Reddit allows anonymous readers very few requests, so we ask slowly, and a failed check is shown on the edition. Claims in posts are labelled Unverified'],
  ['X (Twitter) and 小红书', 'Posts other sources link to; on days a team member runs a search with their own login, a few posts found for a short keyword list', 'Neither offers open read access. Without a login the search is skipped and the edition says so. X posts are shown with X’s own widget'],
];

export default function About() {
  return (
    <>
      <Bar current="about" />
      <JsonLd
        data={{
          '@context': 'https://schema.org',
          '@type': 'AboutPage',
          name: `How ${SITE_NAME} is made`,
          url: abs('/about'),
          publisher: { '@type': 'Organization', name: 'IndusCore', url: 'https://induscore.site' },
        }}
      />
      <div className="wrap">
        <header className="masthead">
          <h1 className="page-title">How this feed is made</h1>
          <p className="tagline">
            One edition a day of what startups are building, raising, launching and debating, with every story linked to
            where it came from.
          </p>
        </header>
        <main id="main" className="prose" style={{ paddingBottom: 56 }}>
          <h2>Every day</h2>
          <p>
            Once a day a member of the IndusCore team runs the aggregation with Claude Code. It reads the sources below,
            keeps what was published in the previous 48 hours (Pacific time), removes duplicates, and ranks what is left.
            Claude Code then reads each candidate&apos;s title and the source&apos;s own description, drops anything off-topic,
            labels what kind of story it is, and writes a one-line context note only when the source supports it. No other
            program or schedule collects stories.
          </p>
          <p>
            Each story appears in one edition only, so a date&apos;s page keeps showing what was new that day. Every edition
            lists which sources were checked and which could not be reached.
          </p>
          <h2>Sources</h2>
          <table>
            <thead>
              <tr>
                <th>Source</th>
                <th>What we read</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {SOURCES.map(([name, what, note]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td>{what}</td>
                  <td>{note}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2>Ranking</h2>
          <p>
            A story&apos;s score combines how recent it is, how much discussion it drew where that is measurable (Hacker
            News points and comments, launch votes, video views, a post&apos;s place in Reddit&apos;s top list), how reliable
            the source is, and whether it is a funding round,
            acquisition or launch. Claude Code may move a story up or down and records why; the reason is shown on the
            story&apos;s page. The three highest scores lead the edition.
          </p>
          <h2>Facts and claims</h2>
          <ul>
            <li>
              <b>Confirmed by the company</b>: the company announced it itself.
            </li>
            <li>
              <b>Reported</b>: a publication reported it.
            </li>
            <li>
              <b>Unverified claim</b>: a founder&apos;s or user&apos;s claim, such as growth figures in a post, that nobody
              independent has checked.
            </li>
            <li>
              <b>Opinion</b>: analysis, predictions and investment theses.
            </li>
          </ul>
          <p>
            Funding amounts, rounds and investors are shown exactly as the linked source states them. We never fill the
            feed with invented stories, engagement numbers, dates or links; a quiet day is a short edition.
          </p>
          <h2>What we store</h2>
          <p>
            The link, title, source, dates, tags and the source&apos;s own short description (at most 400 characters). We do
            not copy articles, images or videos. A story&apos;s picture is the publisher&apos;s own preview image, loaded
            from the publisher&apos;s site (or a company logo from its launch page); when there is none, the card shows a
            plain cover. Videos and X posts appear through the platforms&apos; own players, either because the story is the
            video or post itself or because the story&apos;s source embedded or cited it, and are checked to be about the
            story before they are published. We never store transcripts.
          </p>
          <h2>Follow along</h2>
          <p>
            <HomeLink>Today&apos;s edition</HomeLink> · <Link href="/archive">every past edition</Link> ·{' '}
            <a href="/sv/feed.xml">RSS feed</a> · <a href="/sv/llms.txt">llms.txt</a>
          </p>
          <p>
            Spotted a mistake? Reach the IndusCore team through <a href="https://induscore.site/company">induscore.site</a>{' '}
            with the story link.
          </p>
        </main>
      </div>
    </>
  );
}
