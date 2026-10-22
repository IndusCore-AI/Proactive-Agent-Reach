import Link from 'next/link';

import { CATEGORY_LABEL, CLAIM_LABEL, compactNumber, hostOf, shortDate, storyPath, timePT } from '@/lib/format';
import type { Item, Mention } from '@/lib/types';

import { getXPost } from '@/lib/xpost';

import { XEmbed, YouTubeEmbed } from './Embeds';
import { Thumb } from './Thumb';

/** The biggest discussion of the story (HN points first), if any. */
function topDiscussion(item: Item): Mention | null {
  const ms = (item.mentions ?? []).filter((m) => m.points != null || m.comments != null);
  return ms.sort((a, b) => (b.points ?? 0) - (a.points ?? 0))[0] ?? null;
}

function blurb(item: Item): string | null {
  return item.summary ?? item.excerpt ?? null;
}

function Labels({ item }: { item: Item }) {
  return (
    <div className="labels">
      <span className={`cat cat-${item.category}`}>{CATEGORY_LABEL[item.category]}</span>
      {(item.claim_status === 'unverified' || item.claim_status === 'opinion') && (
        <span className={`claim claim-${item.claim_status}`}>{CLAIM_LABEL[item.claim_status]}</span>
      )}
    </div>
  );
}

function Meta({ item, showEdition }: { item: Item; showEdition?: boolean }) {
  const when = item.published_at ?? item.discovered_at;
  const talk = topDiscussion(item);
  return (
    <div className="meta">
      <span className="pub">{item.source_name}</span>
      <time dateTime={when}>{timePT(when).replace(/^[A-Z][a-z]{2} \d+, /, '')}</time>
      {showEdition && item.feed_date && <Link href={`/${item.feed_date}`}>{shortDate(item.feed_date)}</Link>}
      {talk && (
        <a className="talk" href={talk.url} rel="noopener" target="_blank" title={`Discussion on ${talk.label}`}>
          {talk.label === 'Hacker News' ? 'HN' : talk.label} {talk.points != null ? compactNumber(talk.points) : compactNumber(talk.comments ?? 0)}
        </a>
      )}
      <Link className="more" href={storyPath(item)}>
        Details
      </Link>
    </div>
  );
}

/** The funding facts as a badge over the picture: "$1B · Series A". */
function Badge({ item }: { item: Item }) {
  const f = item.funding;
  if (!f || (!f.amount && !f.round)) return null;
  return <span className="badge">{[f.amount, f.round].filter(Boolean).join(' · ')}</span>;
}

function Picture({ item, eager }: { item: Item; eager?: boolean }) {
  return (
    <a className="pic" href={item.url} rel="noopener" target="_blank" tabIndex={-1} aria-hidden="true">
      <Thumb src={item.image_url} kind={item.image_kind} publisher={item.source_name} category={item.category} eager={eager} />
      <Badge item={item} />
    </a>
  );
}

function Title({ item, as: H = 'h3' }: { item: Item; as?: 'h2' | 'h3' }) {
  return (
    <H className="card-title">
      <a href={item.url} rel="noopener" target="_blank">
        {item.title}
        <span className="sr-only"> (opens {hostOf(item.url)})</span>
      </a>
    </H>
  );
}

/** The day's lead story: big picture, headline, one line of context. */
export function HeroCard({ item }: { item: Item }) {
  const text = blurb(item);
  return (
    <article className="hero" id={`s-${item.id}`}>
      <Picture item={item} eager />
      <div className="hero-body">
        <Labels item={item} />
        <Title item={item} as="h2" />
        {text && <p className="blurb">{text}</p>}
        <Meta item={item} />
      </div>
    </article>
  );
}

export function Card({ item, showEdition = false }: { item: Item; showEdition?: boolean }) {
  const text = blurb(item);
  return (
    <article className="card" id={`s-${item.id}`}>
      <Picture item={item} />
      <div className="card-body">
        <Labels item={item} />
        <Title item={item} />
        {text && <p className="blurb clamp-2">{text}</p>}
        <Meta item={item} showEdition={showEdition} />
      </div>
    </article>
  );
}

/** Discussions: no picture, just the question and how much talk it drew. */
export function CompactRow({ item }: { item: Item }) {
  return (
    <article className="row" id={`s-${item.id}`}>
      <Title item={item} />
      <Meta item={item} />
    </article>
  );
}

/** A post or video the story is about, shown with the platform's own player. */
export async function XPost({ id, title }: { id: string; title: string }) {
  return <XEmbed id={id} title={title} post={await getXPost(id)} />;
}

export function EmbedCard({ item }: { item: Item }) {
  if (!item.embed) return null;
  return (
    <article className="embed-card" id={`e-${item.id}`}>
      {item.embed.type === 'x' ? <XPost id={item.embed.ref} title={item.title} /> : <YouTubeEmbed id={item.embed.ref} title={item.title} />}
      <p className="embed-caption">
        <span className={`cat cat-${item.category}`}>{CATEGORY_LABEL[item.category]}</span>{' '}
        <a href={item.url} rel="noopener" target="_blank">
          {item.title}
        </a>
        <span className="pub"> · {item.source_name}</span>
      </p>
    </article>
  );
}
