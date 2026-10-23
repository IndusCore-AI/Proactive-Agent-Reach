-- Movers to watch: companies, apps and skills gaining traction, kept apart
-- from the daily news. A mover's facts are public; the founders' own take on
-- it lives in mover_notes, a separate table, so no query on movers can ever
-- return it by accident. Stories can point at a mover through mover_items.

create table movers (
    id             text primary key check (id ~ '^[a-z0-9][a-z0-9-]{1,59}$'),   -- the URL slug
    name           text not null check (length(name) between 1 and 120),
    kind           text not null check (kind in ('company', 'app', 'skill')),
    url            text not null check (url ~ '^https?://' and length(url) <= 2048),   -- canonical, like items.url
    one_liner      text not null check (length(one_liner) between 1 and 200),
    summary        text check (length(summary) <= 800),                       -- neutral facts only
    -- [{label, value, source_url, as_of}]: every line carries its source and the date it was true
    traction       jsonb not null default '[]' check (jsonb_typeof(traction) = 'array' and jsonb_array_length(traction) <= 8),
    markets_live   text[] not null default '{}' check (cardinality(markets_live) <= 8),
    claim_status   text not null default 'reported' check (claim_status in ('confirmed', 'reported', 'unverified')),
    tags           text[] not null default '{}' check (cardinality(tags) <= 8),
    image_url      text check (image_url ~ '^https://' and length(image_url) <= 1000),
    image_kind     text check (image_kind in ('cover', 'logo')),
    status         text not null default 'watching' check (status in ('watching', 'archived')),
    added_by       text not null,
    updated_by     text not null,
    first_added_at timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create index movers_status_kind_idx on movers (status, kind);

-- PRIVATE. Read only by /v1/private/movers (its own token) and written only
-- by ingest. Never joined into a public query.
create table mover_notes (
    mover_id   text primary key references movers (id) on delete cascade,
    take       text check (length(take) <= 1500),       -- how it helps us
    learn      text check (length(learn) <= 1000),      -- what to learn from it
    localize   text check (length(localize) <= 1000),   -- where to localize it
    updated_at timestamptz not null default now(),
    updated_by text not null
);

-- Stories that feed a mover.
create table mover_items (
    mover_id text not null references movers (id) on delete cascade,
    item_id  text not null references items (id) on delete cascade,
    added_at timestamptz not null default now(),
    primary key (mover_id, item_id)
);
create index mover_items_item_idx on mover_items (item_id);
