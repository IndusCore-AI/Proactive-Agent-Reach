import Link from 'next/link';

import { CLAIM_LABEL, MOVER_KIND_LABEL, hostOf, moverPath, shortDate } from '@/lib/format';
import { founderName } from '@/lib/unlock';
import type { Mover, MoverNotes, Traction } from '@/lib/types';

import { MoverLogo } from './MoverLogo';

const CARD_TRACTION = 3;

function KindLabels({ mover }: { mover: Mover }) {
  return (
    <div className="labels">
      <span className="kind">{MOVER_KIND_LABEL[mover.kind]}</span>
      {mover.claim_status !== 'confirmed' && <span className="claim">{CLAIM_LABEL[mover.claim_status]}</span>}
    </div>
  );
}

/** Traction facts: the figure, what it counts, and where it is from and when. */
export function TractionList({ lines, large = false }: { lines: Traction[]; large?: boolean }) {
  return (
    <ul className={`traction${large ? ' large' : ''}`}>
      {lines.map((t) => (
        <li key={`${t.label}|${t.source_url}`}>
          <span className="t-value">{t.value}</span>
          <span className="t-label">{t.label}</span>
          <span className="t-src">
            <a href={t.source_url} rel="noopener" target="_blank">
              {hostOf(t.source_url)}
              <span className="sr-only"> (source, opens in a new tab)</span>
            </a>
            {' · '}
            <time dateTime={t.as_of}>as of {shortDate(t.as_of)}</time>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function Markets({ markets }: { markets: string[] }) {
  if (!markets.length) return null;
  return (
    <p className="markets">
      <span>Live in</span> {markets.join(' · ')}
    </p>
  );
}

/** The founders' take. Rendered only on a request that passed currentFounder();
 * `notes` is undefined when this mover has none and `failed` when the private
 * read did not answer. */
export function OurTake({ notes, failed = false }: { notes?: MoverNotes; failed?: boolean }) {
  const parts = notes
    ? ([
        ['How it helps us', notes.take],
        ['What to learn', notes.learn],
        ['Where to localize', notes.localize],
      ].filter(([, v]) => v) as [string, string][])
    : [];
  return (
    <section className="take" aria-label="Our take, founders only">
      <p className="take-kicker">
        <svg width="11" height="11" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path
            fill="currentColor"
            d="M4 7V5a4 4 0 1 1 8 0v2h.5A1.5 1.5 0 0 1 14 8.5v5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 13.5v-5A1.5 1.5 0 0 1 3.5 7H4Zm1.75 0h4.5V5a2.25 2.25 0 0 0-4.5 0v2Z"
          />
        </svg>
        Our take <span>Founders only</span>
      </p>
      {failed ? (
        <p className="take-empty">Couldn&apos;t load our take just now. Reload to try again.</p>
      ) : parts.length ? (
        <dl>
          {parts.map(([label, text]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="take-empty">No take written yet.</p>
      )}
    </section>
  );
}

/** Signs this browser out of the founders' view. A POST form, so it works
 * without JavaScript and no prefetch can ever trigger it. */
export function LockButton() {
  return (
    <form action="/sv/api/founders/lock" method="post" className="lock-form">
      <button type="submit" className="btn">
        Lock
      </button>
    </form>
  );
}

export function FoundersBar({ who }: { who?: string }) {
  return (
    <form action="/sv/api/founders/lock" method="post" className="founders">
      <span className="founders-state">{who ? founderName(who) : 'Founders view'}</span>
      <span aria-hidden="true">·</span>
      <button type="submit" className="founders-lock">
        Lock
      </button>
    </form>
  );
}

/** "3 new stories in the last 14 days": the public trending signal. */
function Trend({ mover }: { mover: Mover }) {
  if (!mover.news_recent) return null;
  return (
    <span className="trend">
      <svg width="11" height="11" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M2 11.5 6.5 7l3 3L14 5.5M10 5.5h4v4" />
      </svg>
      {mover.news_recent} new {mover.news_recent === 1 ? 'story' : 'stories'} in 14 days
    </span>
  );
}

export function MoverCard({
  mover,
  take,
  strip,
}: {
  mover: Mover;
  take?: { notes?: MoverNotes; failed: boolean };
  /** Founders only: score, stage and votes, above the facts. */
  strip?: React.ReactNode;
}) {
  const path = moverPath(mover.id);
  const more = mover.traction.length - CARD_TRACTION;
  return (
    <article className="mover" id={`m-${mover.id}`}>
      {strip}
      <div className="mover-head">
        <MoverLogo src={mover.image_url} kind={mover.image_kind} name={mover.name} />
        <div className="mover-name">
          <KindLabels mover={mover} />
          <h2 className="card-title">
            <Link href={path}>{mover.name}</Link>
          </h2>
        </div>
      </div>
      <p className="blurb">{mover.one_liner}</p>
      {mover.traction.length > 0 && <TractionList lines={mover.traction.slice(0, CARD_TRACTION)} />}
      {more > 0 && (
        <Link className="t-more" href={path}>
          {more} more {more === 1 ? 'figure' : 'figures'}
        </Link>
      )}
      <Markets markets={mover.markets_live} />
      <Trend mover={mover} />
      <div className="meta">
        <a href={mover.url} rel="noopener" target="_blank">
          {hostOf(mover.url)} ↗
        </a>
        {mover.news_count > 0 ? (
          <Link className="more" href={`${path}#news`}>
            Related news: {mover.news_count}
          </Link>
        ) : (
          <span className="more">Related news: 0</span>
        )}
      </div>
      {take && <OurTake notes={take.notes} failed={take.failed} />}
    </article>
  );
}
