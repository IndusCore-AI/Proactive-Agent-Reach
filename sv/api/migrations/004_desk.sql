-- The founders' desk on top of Movers to watch: a queue of proposed movers
-- that only the founders see until one of them publishes it, their votes and
-- reasons, a stage for each mover, a rubric score, and a log of what changed.
--
-- Public stays public and private stays private, as in 003: votes, stages,
-- scores and who did what are in their own tables or in mover_notes, and a
-- public query never joins them. A proposed mover is not on any public page,
-- feed, sitemap or story until a founder publishes it.

alter table movers drop constraint movers_status_check;
alter table movers add constraint movers_status_check check (status in ('proposed', 'watching', 'archived'));

-- PRIVATE, like the rest of mover_notes.
-- score: the office-hours rubric (8 lines, 100 points) for the localized idea,
--   {"total", "lines": {demand, problem, fit, wedge, market, future, moat, whitespace}, "market", "verdict", "scored_at"}
-- stage: where the founders are with it.
alter table mover_notes add column score jsonb check (score is null or jsonb_typeof(score) = 'object');
alter table mover_notes add column stage text not null default 'new'
    check (stage in ('new', 'researching', 'building', 'passed'));
alter table mover_notes alter column updated_by drop not null;

-- PRIVATE. One vote per founder per mover; a reason teaches the next run what to look for.
create table mover_votes (
    mover_id   text not null references movers (id) on delete cascade,
    voter      text not null check (voter ~ '^[a-z][a-z0-9-]{0,31}$'),
    vote       smallint not null check (vote in (-1, 1)),
    reason     text check (length(reason) <= 500),
    updated_at timestamptz not null default now(),
    primary key (mover_id, voter)
);

-- What changed, newest first. Rows with private = false are the public
-- "added to the list" and "new stories" lines, served without actor or
-- detail; everything else is for the founders only.
create table mover_events (
    id       bigserial primary key,
    mover_id text not null references movers (id) on delete cascade,
    at       timestamptz not null default now(),
    kind     text not null check (kind in ('proposed', 'added', 'news', 'vote', 'stage', 'scored', 'archived')),
    actor    text not null,
    detail   jsonb not null default '{}' check (jsonb_typeof(detail) = 'object'),
    private  boolean not null
);
create index mover_events_at_idx on mover_events (at desc);
create index mover_events_mover_idx on mover_events (mover_id, at desc);

-- Movers already on the list count as added when they were first added.
insert into mover_events (mover_id, at, kind, actor, private)
select id, first_added_at, 'added', added_by, false from movers where status = 'watching';
