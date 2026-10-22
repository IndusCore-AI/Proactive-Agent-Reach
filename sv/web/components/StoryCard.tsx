import Link from 'next/link';

import { CATEGORY_LABEL, CLAIM_LABEL, compactNumber, fundingLine, hostOf, storyPath, tagLabel, timePT } from '@/lib/format';
import type { Item } from '@/lib/types';

import { XEmbed, YouTubeEmbed } from './Embeds';

function Engagement({ points, comments }: { points: number | null; comments: number | null }) {
  const bits = [];
  if (points != null) bits.push(`${compactNumber(points)} points`);
  if (comments != null) bits.push(`${compactNumber(comments)} comments`);
  return bits.length ? <span className="meta"> · {bits.join(' · ')}</span> : null;
}

export function StoryCard({ item, headingLevel = 3, showEdition = false }: { item: Item; headingLevel?: 2 | 3; showEdition?: boolean }) {
  const H = `h${headingLevel}` as 'h2' | 'h3';
  const publisher = item.source_name;
  const via = item.mentions?.filter((m) => m.url !== item.url) ?? [];
  const when = item.published_at ?? item.discovered_at;
  return (
    <li className="story" id={`s-${item.id}`}>
      <div className="labels">
        <span className={`cat cat-${item.category}`}>{CATEGORY_LABEL[item.category]}</span>
        {item.claim_status !== 'reported' && (
          <span className={`claim claim-${item.claim_status}`}>{CLAIM_LABEL[item.claim_status]}</span>
        )}
      </div>
      <H className="story-title">
        <a href={item.url} rel="noopener" target="_blank">
          {item.title}
          <span className="ext" aria-hidden="true">↗</span>
          <span className="sr-only"> (opens {hostOf(item.url)})</span>
        </a>
      </H>
      <p className="byline">
        <span className="pub">{publisher}</span>
        {item.author && <span>by {item.author}</span>}
        <time dateTime={when} title={item.published_at ? 'Published' : 'First seen (the source gives no date)'}>
          {item.published_at ? timePT(when) : `Seen ${timePT(when)}`}
        </time>
        {showEdition && item.feed_date && <Link href={`/${item.feed_date}`}>Edition of {item.feed_date}</Link>}
      </p>
      {item.summary && (
        <p className="context">
          <b>Context:</b> {item.summary}
        </p>
      )}
      {item.excerpt && (
        <p className="excerpt">
          <span className="sr-only">From the source: </span>
          <q>{item.excerpt}</q>
        </p>
      )}
      {item.funding && (
        <p className="facts">
          {fundingLine(item.funding)}
          <small>As stated by {publisher}{item.claim_status === 'confirmed' ? ', confirmed by the company' : ''}.</small>
        </p>
      )}
      {item.embed?.type === 'x' && <XEmbed id={item.embed.ref} title={item.title} url={item.url} />}
      {item.embed?.type === 'youtube' && <YouTubeEmbed id={item.embed.ref} title={item.title} />}
      <ul className="links">
        <li>
          <a href={item.url} rel="noopener" target="_blank">
            Read at {hostOf(item.url) || publisher}
          </a>
        </li>
        {via.slice(0, 3).map((m) => (
          <li key={m.url}>
            <a href={m.url} rel="noopener" target="_blank">
              {m.label}
            </a>
            <Engagement points={m.points} comments={m.comments} />
          </li>
        ))}
        <li>
          <Link href={storyPath(item)}>Details</Link>
        </li>
      </ul>
      {item.tags.length > 0 && (
        <ul className="tags" aria-label="Topics">
          {item.tags.map((t) => (
            <li key={t}>
              <Link href={`/topics/${t}`}>#{tagLabel(t)}</Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
