-- Keeping Up with Silicon Valley: initial schema.
--
-- Only metadata needed to show, deduplicate and archive a story is stored:
-- never media, never article bodies. `excerpt` is the source's own short
-- description (feed summary / meta description), capped at 400 characters;
-- `summary` is a grounded one-line context written during curation.

create table items (
    id            text primary key,            -- 12 chars of base32(sha256(url)), stable across reruns
    url           text not null unique,        -- canonical original URL
    dedupe_key    text not null,               -- normalized title, for near-identical stories
    source        text not null,               -- platform slug: hackernews, techcrunch, producthunt, yc, reddit, ...
    source_name   text not null,               -- display name, e.g. "TechCrunch"
    title         text not null check (length(title) between 3 and 300),
    excerpt       text check (length(excerpt) <= 400),
    summary       text check (length(summary) <= 400),
    author        text check (length(author) <= 120),
    published_at  timestamptz,                 -- as stated by the source; null when it gives none
    discovered_at timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    category      text not null check (category in
                    ('funding', 'acquisition', 'launch', 'news', 'discussion', 'analysis')),
    tags          text[] not null default '{}',
    claim_status  text not null default 'reported' check (claim_status in
                    ('confirmed', 'reported', 'unverified', 'opinion')),
    funding       jsonb,                       -- {company, round, amount, currency, investors[]} as stated by the source
    embed_type    text check (embed_type in ('x', 'youtube')),
    embed_ref     text check (embed_ref ~ '^[A-Za-z0-9_-]{1,64}$'),
    score         real not null default 0,
    score_detail  jsonb,                       -- components that produced `score`, so a rank can be explained
    search        tsvector generated always as (
                      setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                      setweight(to_tsvector('english', coalesce(summary, '') || ' ' || coalesce(excerpt, '')), 'B') ||
                      setweight(to_tsvector('english', coalesce(source_name, '')), 'C')
                  ) stored
);
create index items_dedupe_key_idx   on items (dedupe_key);
create index items_published_at_idx on items (published_at desc);
create index items_search_idx       on items using gin (search);
create index items_tags_idx         on items using gin (tags);

-- Where else a story was seen: the Hacker News thread for a TechCrunch
-- article, a Reddit discussion, the Product Hunt page. Engagement is what the
-- source showed at observed_at, never extrapolated.
create table mentions (
    item_id     text not null references items (id) on delete cascade,
    url         text not null,
    source      text not null,
    label       text not null,
    points      integer check (points >= 0),
    comments    integer check (comments >= 0),
    observed_at timestamptz not null default now(),
    primary key (item_id, url)
);

create table runs (
    id             uuid primary key,
    feed_date      date not null,
    operator       text not null,
    status         text not null default 'running' check (status in ('running', 'complete', 'partial', 'failed')),
    started_at     timestamptz not null default now(),
    finished_at    timestamptz,
    sources        jsonb not null default '[]',   -- [{source, ok, fetched, kept, error}]
    errors         jsonb not null default '[]',
    items_received integer not null default 0,
    items_inserted integer not null default 0,
    items_updated  integer not null default 0,
    items_merged   integer not null default 0,
    items_rejected integer not null default 0,
    notes          text
);
create index runs_feed_date_idx on runs (feed_date, started_at desc);

-- One row per story per edition. An item belongs to exactly one edition
-- (enforced on ingest), so overlapping collection windows never repeat a story.
create table feed_entries (
    feed_date date not null,
    item_id   text not null references items (id) on delete cascade,
    rank      integer not null default 0,
    score     real not null default 0,
    run_id    uuid references runs (id) on delete set null,
    added_at  timestamptz not null default now(),
    primary key (feed_date, item_id)
);
create unique index feed_entries_item_idx on feed_entries (item_id);
create index feed_entries_rank_idx on feed_entries (feed_date, rank);

create table ingest_tokens (
    name        text primary key,               -- the operator: pulkit, michael
    token_hash  text not null unique,           -- sha256 hex; the token itself is never stored
    created_at  timestamptz not null default now(),
    revoked_at  timestamptz
);
