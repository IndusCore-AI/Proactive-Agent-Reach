import Link from 'next/link';

import { CopyPrompt } from '@/components/CopyPrompt';
import { MoverLogo } from '@/components/MoverLogo';
import { MOVER_KIND_LABEL, moverPath, shortDate, timePT } from '@/lib/format';
import { RUBRIC, band, type NextStep } from '@/lib/nextSteps';
import { founderName } from '@/lib/unlock';
import type { DeskEvent, DeskMover, DeskUpdate, MoverStage, MoverStatus, Score, Vote } from '@/lib/types';

// The founders' desk. Every component here renders only on a request that
// passed currentFounder() (the pages check), from data fetched with the
// founders token. Forms post to /sv/api/founders/movers/{id}/{action} and
// work without JavaScript.

export const STAGES: { key: MoverStage; label: string }[] = [
  { key: 'new', label: 'New' },
  { key: 'researching', label: 'Researching' },
  { key: 'building', label: 'Building' },
  { key: 'passed', label: 'Passed' },
];
const STAGE_LABEL = Object.fromEntries(STAGES.map((s) => [s.key, s.label])) as Record<MoverStage, string>;
export const STATUS_LABEL: Record<MoverStatus, string> = { proposed: 'Waiting for a decision', watching: 'On the public list', archived: 'Archived' };

function action(id: string, name: 'vote' | 'stage' | 'status'): string {
  return `/sv/api/founders/movers/${id}/${name}`;
}

function when(ts: string): string {
  return timePT(ts);
}

function Arrow({ up }: { up: boolean }) {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path fill="currentColor" d={up ? 'M8 3.5 14 11H2z' : 'M8 12.5 2 5h12z'} />
    </svg>
  );
}

export function ScorePill({ score, large = false }: { score: Score | null; large?: boolean }) {
  if (!score) return <span className={`score-pill none${large ? ' large' : ''}`}>Not scored</span>;
  const b = band(score.total);
  return (
    <span className={`score-pill ${b.key}${large ? ' large' : ''}`} title={`${score.total} of 100 for ${score.market}: ${b.label.toLowerCase()}`}>
      <strong>{score.total}</strong>
      <span>{b.label}</span>
    </span>
  );
}

export function StagePill({ stage }: { stage: MoverStage }) {
  return <span className={`stage-pill ${stage}`}>{STAGE_LABEL[stage]}</span>;
}

export function VoteSummary({ votes }: { votes: Vote[] }) {
  if (!votes.length) return <span className="votes none">No votes yet</span>;
  return (
    <span className="votes">
      {votes.map((v) => (
        <span key={v.voter} className={`vote ${v.vote > 0 ? 'up' : 'down'}`} title={v.reason ?? undefined}>
          <Arrow up={v.vote > 0} />
          {founderName(v.voter)}
        </span>
      ))}
    </span>
  );
}

/** Score, stage and votes in one line, for a card on the desk. */
export function DeskStrip({ mover }: { mover: DeskMover }) {
  return (
    <div className="desk-strip">
      <ScorePill score={mover.score} />
      <StagePill stage={mover.stage} />
      <VoteSummary votes={mover.votes} />
    </div>
  );
}

function VoteButtons({ mover, me, back, compact = false }: { mover: DeskMover; me: string; back: string; compact?: boolean }) {
  const mine = mover.votes.find((v) => v.voter === me)?.vote ?? 0;
  return (
    <form action={action(mover.id, 'vote')} method="post" className="vote-form">
      <input type="hidden" name="back" value={back} />
      {/* Pressing a side always sets it (and saves the reason), so adding a
          reason to a vote already cast never takes the vote back by accident. */}
      <div className="seg" role="group" aria-label="Your vote">
        <button type="submit" name="vote" value="1" className="seg-btn up" aria-pressed={mine === 1} title={compact ? 'Worth it' : undefined}>
          <Arrow up />
          {compact ? <span className="sr-only">Worth it</span> : 'Worth it'}
        </button>
        <button type="submit" name="vote" value="-1" className="seg-btn down" aria-pressed={mine === -1} title={compact ? 'Not for us' : undefined}>
          <Arrow up={false} />
          {compact ? <span className="sr-only">Not for us</span> : 'Not for us'}
        </button>
      </div>
      {!compact && (
        <>
          <label className="reason">
            <span>Why (optional, teaches the next run)</span>
            <input type="text" name="reason" maxLength={500} placeholder="e.g. great wedge, but no buyer we can reach" />
          </label>
          {mine !== 0 && (
            <button type="submit" name="vote" value="0" className="link-btn">
              Take back my vote
            </button>
          )}
        </>
      )}
    </form>
  );
}

function StatusButton({ mover, to, back, children, primary = false }: { mover: DeskMover; to: MoverStatus; back: string; children: React.ReactNode; primary?: boolean }) {
  return (
    <form action={action(mover.id, 'status')} method="post" className="inline-form">
      <input type="hidden" name="back" value={back} />
      <input type="hidden" name="status" value={to} />
      <button type="submit" className={`btn${primary ? ' primary' : ''}`}>
        {children}
      </button>
    </form>
  );
}

/** One proposed mover in the queue: what it is, our score, and the call. */
export function QueueRow({ mover, me, back }: { mover: DeskMover; me: string; back: string }) {
  return (
    <li className="queue-row">
      <MoverLogo src={mover.image_url} kind={mover.image_kind} name={mover.name} />
      <div className="queue-main">
        <div className="labels">
          <span className="kind">{MOVER_KIND_LABEL[mover.kind]}</span>
          {mover.score && <span className="queue-market">for {mover.score.market}</span>}
        </div>
        <h3 className="card-title">
          <Link href={moverPath(mover.id)}>{mover.name}</Link>
        </h3>
        <p className="blurb">{mover.one_liner}</p>
        {mover.score?.verdict && <p className="verdict">{mover.score.verdict}</p>}
      </div>
      <div className="queue-side">
        <ScorePill score={mover.score} />
        <VoteSummary votes={mover.votes} />
        <div className="queue-actions">
          <VoteButtons mover={mover} me={me} back={back} compact />
          <StatusButton mover={mover} to="watching" back={back} primary>
            Publish
          </StatusButton>
          <StatusButton mover={mover} to="archived" back={back}>
            Pass
          </StatusButton>
        </div>
      </div>
    </li>
  );
}

/** The decision panel on a mover's page: status, your vote and why, the stage. */
export function DecisionPanel({ mover, me, failed }: { mover: DeskMover; me: string; failed: boolean }) {
  const back = `${moverPath(mover.id)}#decide`;
  return (
    <section className="decide" id="decide" aria-labelledby="decide-head">
      <div className="decide-head">
        <h2 id="decide-head" className="sub-head">
          Decide
        </h2>
      </div>
      {failed && (
        <p className="decide-error" role="alert">
          That didn&apos;t save. Try again; if it keeps failing, the feed API may be down.
        </p>
      )}
      <div className="decide-row">
        <span className="decide-label">List</span>
        <div className="decide-controls">
          {mover.status === 'proposed' && (
            <>
              <StatusButton mover={mover} to="watching" back={back} primary>
                Publish to the list
              </StatusButton>
              <StatusButton mover={mover} to="archived" back={back}>
                Pass
              </StatusButton>
            </>
          )}
          {mover.status === 'watching' && (
            <StatusButton mover={mover} to="archived" back={back}>
              Take off the list
            </StatusButton>
          )}
          {mover.status === 'archived' && (
            <StatusButton mover={mover} to="proposed" back={back}>
              Back to the queue
            </StatusButton>
          )}
          <span className="decide-note">
            {mover.status === 'proposed' ? 'Only the two of you can see it until it is published.' : mover.status === 'watching' ? 'Public facts only; our take stays here.' : 'Hidden everywhere.'}
          </span>
        </div>
      </div>
      <div className="decide-row">
        <span className="decide-label">Your vote</span>
        <div className="decide-controls">
          <VoteButtons mover={mover} me={me} back={back} />
        </div>
      </div>
      <div className="decide-row">
        <span className="decide-label">Stage</span>
        <form action={action(mover.id, 'stage')} method="post" className="decide-controls">
          <input type="hidden" name="back" value={back} />
          <div className="seg" role="group" aria-label="Stage">
            {STAGES.map((s) => (
              <button key={s.key} type="submit" name="stage" value={s.key} className="seg-btn" aria-pressed={mover.stage === s.key}>
                {s.label}
              </button>
            ))}
          </div>
        </form>
      </div>
      {mover.votes.length > 0 && (
        <ul className="vote-list">
          {mover.votes.map((v) => (
            <li key={v.voter}>
              <span className={`vote ${v.vote > 0 ? 'up' : 'down'}`}>
                <Arrow up={v.vote > 0} />
                {founderName(v.voter)}
              </span>
              {v.reason ? <q>{v.reason}</q> : <span className="muted">no reason given</span>}
              <time dateTime={v.at}>{when(v.at)}</time>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Our office-hours score, line by line. */
export function ScoreCard({ score }: { score: Score | null }) {
  return (
    <section className="score-card" aria-labelledby="score-head">
      <div className="decide-head">
        <h2 id="score-head" className="sub-head">
          Fit for us
        </h2>
        <span className="muted">Office-hours rubric, 100 points</span>
      </div>
      {score ? (
        <>
          <div className="score-top">
            <ScorePill score={score} large />
            <div>
              <p className="score-market">For {score.market}</p>
              {score.verdict && <p className="verdict">{score.verdict}</p>}
              {score.scored_at && (
                <p className="muted">
                  Scored {shortDate(score.scored_at)}
                  {score.scored_by ? ` by ${founderName(score.scored_by)}` : ''}
                </p>
              )}
            </div>
          </div>
          <ul className="rubric">
            {RUBRIC.map((r) => {
              const n = score.lines[r.key];
              return (
                <li key={r.key}>
                  <span className="r-label">{r.label}</span>
                  <span className="r-bar" aria-hidden="true">
                    <span style={{ width: `${(n / r.max) * 100}%` }} />
                  </span>
                  <span className="r-n">
                    {n}
                    <span>/{r.max}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      ) : (
        <p className="take-empty">Not scored yet. The &ldquo;Score it&rdquo; prompt below runs office hours and puts the score here.</p>
      )}
    </section>
  );
}

/** Ready-to-run prompts for the next step. */
export function NextSteps({ steps }: { steps: NextStep[] }) {
  return (
    <section className="next-steps" aria-labelledby="next-head">
      <div className="decide-head">
        <h2 id="next-head" className="sub-head">
          Next step
        </h2>
        <span className="muted">Copy one into Claude Code</span>
      </div>
      <ul>
        {steps.map((s) => (
          <li key={s.key} className="step">
            <div className="step-head">
              <div>
                <h3>{s.title}</h3>
                <p>{s.why}</p>
              </div>
              <CopyPrompt text={s.prompt} label={s.title} />
            </div>
            <details>
              <summary>See the prompt</summary>
              <pre>{s.prompt}</pre>
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}

const EVENT_TEXT: Record<DeskEvent['kind'], (e: DeskEvent) => string> = {
  proposed: () => 'proposed it',
  added: (e) => (e.detail.from === 'proposed' ? 'published it to the list' : e.detail.from === 'archived' ? 'put it back on the list' : 'added it to the list'),
  news: (e) => `linked ${e.detail.count ?? 'new'} ${e.detail.count === 1 ? 'story' : 'stories'}`,
  vote: (e) => (e.detail.vote === 0 ? 'took back their vote' : `voted ${e.detail.vote === 1 ? 'worth it' : 'not for us'}${e.detail.reason ? `: “${e.detail.reason}”` : ''}`),
  stage: (e) => `moved it to ${STAGE_LABEL[e.detail.to as MoverStage] ?? e.detail.to}`,
  scored: (e) => `scored it ${e.detail.total} for ${e.detail.market}`,
  archived: () => 'took it off the list',
};

export function eventText(e: DeskEvent): string {
  return EVENT_TEXT[e.kind](e);
}

export function History({ events }: { events: DeskEvent[] }) {
  if (!events.length) return null;
  return (
    <section className="history" aria-labelledby="history-head">
      <h2 id="history-head" className="sub-head">
        History
      </h2>
      <ol>
        {events.map((e) => (
          <li key={e.id}>
            <time dateTime={e.at}>{when(e.at)}</time>
            <span>
              <strong>{founderName(e.actor)}</strong> {eventText(e)}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** The full log on /movers/updates for founders. */
export function DeskUpdates({ updates }: { updates: DeskUpdate[] }) {
  return (
    <ol className="updates">
      {updates.map((u) => (
        <li key={u.id} className={u.private ? 'private' : undefined}>
          <time dateTime={u.at}>{when(u.at)}</time>
          <span>
            <strong>{founderName(u.actor)}</strong> {eventText(u)}{' '}
            {u.status === 'archived' ? <span className="muted">{u.name}</span> : <Link href={moverPath(u.mover_id)}>{u.name}</Link>}
            {u.private && <span className="only-us">Founders only</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}
