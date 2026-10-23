-- The founders' research, next to the desk: one row per research run (a
-- prompt from a founders' call, a lead, a rerun on new sources) with its
-- verdict, how it was found, what it found and its sources, and every idea it
-- scored on the office-hours rubric. That includes the ideas under the 40
-- cutoff, which never reach the desk queue.
--
-- PRIVATE, all of it. Only /v1/private/research serves it, and no public
-- query joins these tables.

create table research_runs (
    id         text primary key check (id ~ '^[a-z0-9][a-z0-9-]{1,59}$'),
    title      text not null check (length(title) between 1 and 160),
    run_date   date not null,
    -- makes_list: at least one idea at 40 or more; below_cutoff: scored, none
    -- made it; no: a verdict without a score; replaced: folded into another
    -- run; input: a long list or sweep that fed other runs
    outcome    text not null check (outcome in ('makes_list', 'below_cutoff', 'no', 'replaced', 'input')),
    verdict    text not null check (length(verdict) between 1 and 120),
    summary    text check (length(summary) <= 1500),
    method     text check (length(method) <= 1500),
    findings   jsonb not null default '[]' check (jsonb_typeof(findings) = 'array'),  -- [{group, title, text}]
    sources    jsonb not null default '[]' check (jsonb_typeof(sources) = 'array'),   -- [{label, url}]
    refs       jsonb not null default '[]' check (jsonb_typeof(refs) = 'array'),      -- files and teamctx ids
    position   integer not null default 0,
    added_by   text not null,
    updated_by text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Each idea is our localized version for one named market, scored on the
-- rubric (teamctx k:878). lines is null when only the total was recorded.
create table research_ideas (
    id       bigserial primary key,
    run_id   text not null references research_runs (id) on delete cascade,
    position integer not null,
    idea     text not null check (length(idea) between 1 and 200),
    market   text not null check (length(market) between 1 and 120),
    total    smallint not null check (total between 0 and 100),
    lines    jsonb check (lines is null or jsonb_typeof(lines) = 'object'),
    note     text check (length(note) <= 300),
    mover_id text references movers (id) on delete set null,
    unique (run_id, position)
);
create index research_ideas_total_idx on research_ideas (total desc);
