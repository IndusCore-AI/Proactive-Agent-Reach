import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { Bar, HomeLink } from '@/components/Chrome';
import { STATUS_LABEL } from '@/components/Desk';
import { FoundersBar } from '@/components/Movers';
import { getResearch } from '@/lib/api';
import { currentFounder } from '@/lib/founders';
import { abs, moverPath, shortDate } from '@/lib/format';
import { RUBRIC, band } from '@/lib/nextSteps';
import { OUTCOME_LABEL, board, groupFindings, linesText, researchStats, type BoardRow } from '@/lib/research';
import type { ResearchRun } from '@/lib/types';

// The founders' research: every research run (a prompt from a founders' call,
// a lead, a rerun) with its verdict, how it was found and what it found, and
// every idea it scored, including those under the cutoff that never reach the
// queue. PRIVATE: an unlocked browser only; anyone else gets a 404. Per
// request, never cached.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Research',
  alternates: { canonical: abs('/movers/research') },
  robots: { index: false, follow: false, nocache: true },
};

type SP = Promise<Record<string, string | string[] | undefined>>;

function one(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

function href(q: { run?: string; only?: string }): string {
  const p = new URLSearchParams();
  if (q.run) p.set('run', q.run);
  if (q.only) p.set('only', q.only);
  const s = p.toString();
  return `/movers/research${s ? `?${s}` : ''}#ideas`;
}

function IdeaScore({ total }: { total: number }) {
  const b = band(total);
  return (
    <span className={`score-pill ${b.key}`} title={`${total} of 100: ${b.label.toLowerCase()}`}>
      <strong>{total}</strong>
      <span>{b.label}</span>
    </span>
  );
}

function IdeaPlace({ row, cutoff }: { row: BoardRow; cutoff: number }) {
  if (row.mover) {
    return (
      <Link className={`rb-place on ${row.mover.status}`} href={moverPath(row.mover.id)}>
        {STATUS_LABEL[row.mover.status]}
      </Link>
    );
  }
  return <span className="rb-place">{row.total >= cutoff ? 'Not on the desk' : 'Off the list'}</span>;
}

function Board({ rows, cutoff, showRun }: { rows: BoardRow[]; cutoff: number; showRun: boolean }) {
  if (!rows.length) return <p className="empty">No ideas match this filter.</p>;
  const firstBelow = rows.findIndex((r) => r.total < cutoff);
  return (
    <ol className="research-board">
      {rows.map((r, n) => {
        const lines = linesText(r.lines);
        return (
          <li key={`${r.run.id}-${r.position}`} className="rb-item">
            {n === firstBelow && (
              <p className="rb-cut">
                Cutoff {cutoff}. Everything below stays off the list.
              </p>
            )}
            <div className={`rb-row${r.total < cutoff ? ' below' : ''}`}>
              <IdeaScore total={r.total} />
              <div className="rb-main">
                <p className="rb-idea">{r.idea}</p>
                <p className="rb-meta">
                  <span>{r.market}</span>
                  {showRun && (
                    <>
                      <span aria-hidden="true">·</span>
                      <a href={`#${r.run.id}`}>{r.run.title}</a>
                    </>
                  )}
                  {lines && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span className="rb-lines" aria-label={lines.spoken} title={lines.spoken}>
                        {lines.short}
                      </span>
                    </>
                  )}
                </p>
                {r.note && <p className="rb-note">{r.note}</p>}
              </div>
              <IdeaPlace row={r} cutoff={cutoff} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function Run({ run, cutoff }: { run: ResearchRun; cutoff: number }) {
  const best = run.ideas.reduce((b, i) => Math.max(b, i.total), -1);
  const made = run.ideas.filter((i) => i.total >= cutoff).length;
  return (
    <article className="run-card" id={run.id} aria-labelledby={`${run.id}-title`}>
      <div className="run-head">
        <h3 id={`${run.id}-title`}>{run.title}</h3>
        <span className={`outcome ${run.outcome}`}>
          <span className="sr-only">{OUTCOME_LABEL[run.outcome]}: </span>
          {run.verdict}
        </span>
      </div>
      <p className="run-meta">
        {shortDate(run.run_date)}
        {run.ideas.length > 0 && (
          <>
            {' · '}
            <Link href={href({ run: run.id })}>
              {run.ideas.length} {run.ideas.length === 1 ? 'idea' : 'ideas'} scored, best {best}
              {made ? `, ${made} at ${cutoff} or more` : ''}
            </Link>
          </>
        )}
      </p>
      {run.summary && <p className="run-summary">{run.summary}</p>}
      {run.method && (
        <p className="run-method">
          <strong>How we found it.</strong> {run.method}
        </p>
      )}
      {groupFindings(run.findings).map((g, n) => (
        <div key={n} className="run-findings">
          {g.group && <h4 className="sub-head">{g.group}</h4>}
          <ul>
            {g.items.map((f, k) => (
              <li key={k}>
                {f.title && <strong>{f.title}</strong>} {f.text}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {(run.sources.length > 0 || run.refs.length > 0) && (
        <p className="run-sources">
          {run.sources.map((s, n) => (
            <span key={s.url}>
              {n > 0 && ' · '}
              <a href={s.url} rel="noopener noreferrer" target="_blank">
                {s.label}
              </a>
            </span>
          ))}
          {run.refs.length > 0 && <span className="run-refs">{run.sources.length ? ' · ' : ''}{run.refs.join(', ')}</span>}
        </p>
      )}
    </article>
  );
}

export default async function Research({ searchParams }: { searchParams: SP }) {
  const me = await currentFounder();
  if (!me) notFound();
  const data = await getResearch();
  const sp = await searchParams;

  const runs = data?.runs ?? [];
  const cutoff = data?.cutoff ?? 40;
  const runFilter = runs.some((r) => r.id === one(sp.run) && r.ideas.length) ? one(sp.run) : undefined;
  const only = one(sp.only) === 'list' ? 'list' : undefined;
  const rows = board(runs, { run: runFilter, atLeast: only ? cutoff : undefined });
  const stats = researchStats(runs, cutoff);
  const scoredRuns = runs.filter((r) => r.ideas.length);

  return (
    <>
      <Bar current="movers" />
      <div className="wrap">
        <ol className="crumbs">
          <li>
            <HomeLink>Today</HomeLink>
          </li>
          <li>
            <Link href="/movers">Movers to watch</Link>
          </li>
          <li aria-current="page">Research</li>
        </ol>
        <header className="masthead compact movers-head">
          <div>
            <p className="kicker">Founders&apos; desk</p>
            <h1 className="page-title">Research</h1>
            <p className="tagline">
              Every research run and every idea it scored, including the ones under the cutoff that never reach the queue. Only the two of you see this page.
            </p>
          </div>
          <FoundersBar who={me} />
        </header>
        <main id="main" className="front desk research">
          {!data ? (
            <p className="notice">Couldn&apos;t load the research just now. Reload to try again.</p>
          ) : !runs.length ? (
            <p className="empty">
              No research recorded yet. A run records its write-up with <code>ingest.py research</code>.
            </p>
          ) : (
            <>
              <ul className="desk-stats" aria-label="At a glance">
                <li>
                  <a href="#runs">
                    <strong>{stats.runs}</strong>
                    <span>Research runs</span>
                  </a>
                </li>
                <li>
                  <Link href={href({})}>
                    <strong>{stats.ideas}</strong>
                    <span>Ideas scored</span>
                  </Link>
                </li>
                <li>
                  <Link href={href({ only: 'list' })}>
                    <strong>{stats.atCutoff}</strong>
                    <span>At {cutoff} or more</span>
                  </Link>
                </li>
                {stats.best && (
                  <li>
                    <Link href={href({})}>
                      <strong>{stats.best.total}</strong>
                      <span>Best: {stats.best.idea}</span>
                    </Link>
                  </li>
                )}
              </ul>

              <section className="section score-card how-scored" aria-labelledby="how-head">
                <div className="decide-head">
                  <h2 id="how-head" className="sub-head">
                    How ideas are scored
                  </h2>
                  <span className="muted">Office-hours rubric, 100 points</span>
                </div>
                <ul className="rubric">
                  {RUBRIC.map((r) => (
                    <li key={r.key}>
                      <span className="r-label">{r.label}</span>
                      <span className="r-bar" aria-hidden="true">
                        <span style={{ width: `${(r.max / 25) * 100}%` }} />
                      </span>
                      <span className="r-n">{r.max}</span>
                    </li>
                  ))}
                </ul>
                <ul className="how-rules">
                  <li>Each idea is our localized version for one named market, not the original product.</li>
                  <li>Demand only counts evidence from that market, so an idea nobody there has asked us for scores 0 on demand.</li>
                  <li>Under {cutoff} an idea stays off the list. 55 is worth interviews, 70 is strong. A paid test adds 13.</li>
                </ul>
              </section>

              <section className="section" id="ideas" aria-labelledby="ideas-head">
                <div className="section-head">
                  <h2 id="ideas-head">Every idea, ranked</h2>
                  <span>Line scores read demand / problem / fit / wedge / market / future / defensibility / whitespace.</span>
                </div>
                <div className="filters">
                  <ul className="chips" aria-label="Filter by run">
                    <li>
                      <Link className="chip" href={href({ only })} aria-current={!runFilter ? 'true' : undefined}>
                        All runs <span className="n">{stats.ideas}</span>
                      </Link>
                    </li>
                    {scoredRuns.map((r) => (
                      <li key={r.id}>
                        <Link className="chip" href={href({ run: r.id, only })} aria-current={runFilter === r.id ? 'true' : undefined}>
                          {r.title} <span className="n">{r.ideas.length}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                  <ul className="chips" aria-label="Show">
                    <li>
                      <Link className="chip" href={href({ run: runFilter })} aria-current={!only ? 'true' : undefined}>
                        Every score
                      </Link>
                    </li>
                    <li>
                      <Link className="chip" href={href({ run: runFilter, only: 'list' })} aria-current={only ? 'true' : undefined}>
                        Only {cutoff} and over
                      </Link>
                    </li>
                  </ul>
                </div>
                <Board rows={rows} cutoff={cutoff} showRun={!runFilter} />
              </section>

              <section className="section" id="runs" aria-labelledby="runs-head">
                <div className="section-head">
                  <h2 id="runs-head">What each run found</h2>
                  <span>Newest first.</span>
                </div>
                <div className="runs">
                  {runs.map((r) => (
                    <Run key={r.id} run={r} cutoff={cutoff} />
                  ))}
                </div>
              </section>
            </>
          )}
        </main>
      </div>
    </>
  );
}
