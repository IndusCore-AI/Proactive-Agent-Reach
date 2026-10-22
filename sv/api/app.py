"""Keeping Up with Silicon Valley: read + ingest API over the induscore_sv
database. Runs on the prod VM on 127.0.0.1 only; the public site reaches it
through its own Cloudflare quick tunnel (see ../ops).

Two kinds of caller, two kinds of token:
  read    the Vercel server (SV_READ_TOKEN_SHA256 in the env file)
  ingest  a founder's Claude Code run (rows in ingest_tokens, one per person)
Tokens are compared by sha256, so neither the env file nor the database holds
a usable secret.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Query
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field, field_validator, model_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "aggregate-silicon-valley" / "scripts"))
import svlib  # noqa: E402  (the one copy of the URL / duplicate rules, shared with the skill)

DATABASE_URL = os.environ.get("SV_DATABASE_URL", "postgresql:///induscore_sv")
READ_TOKEN_SHA256 = os.environ.get("SV_READ_TOKEN_SHA256", "")
FIRST_EDITION = date(2026, 1, 1)
STALE_RUN = timedelta(hours=3)

Category = Literal["funding", "acquisition", "launch", "news", "discussion", "analysis"]
ClaimStatus = Literal["confirmed", "reported", "unverified", "opinion"]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")]

pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=8, open=False, kwargs={"row_factory": dict_row})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    pool.open(wait=True, timeout=10)
    yield
    pool.close()


app = FastAPI(title="Keeping Up with Silicon Valley API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def _sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    return authorization[7:].strip()


def require_read(authorization: Annotated[str | None, Header()] = None) -> None:
    token = _bearer(authorization)
    if not READ_TOKEN_SHA256 or not hmac.compare_digest(_sha256(token), READ_TOKEN_SHA256):
        raise HTTPException(403, "invalid read token")


def require_ingest(authorization: Annotated[str | None, Header()] = None) -> str:
    token_hash = _sha256(_bearer(authorization))
    with pool.connection() as conn:
        row = conn.execute(
            "select name from ingest_tokens where token_hash = %s and revoked_at is null", (token_hash,)
        ).fetchone()
    if not row:
        raise HTTPException(403, "invalid ingest token")
    return row["name"]


# ---------------------------------------------------------------- payloads

class Funding(BaseModel):
    company: str = Field(min_length=1, max_length=120)
    round: str | None = Field(default=None, max_length=40)
    amount: str | None = Field(default=None, max_length=40)          # as the source states it: "$12M"
    amount_usd: float | None = Field(default=None, ge=0, le=1e12)
    investors: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=12)


class Mention(BaseModel):
    url: str
    source: Slug
    label: str = Field(min_length=1, max_length=80)
    points: int | None = Field(default=None, ge=0, le=10_000_000)
    comments: int | None = Field(default=None, ge=0, le=10_000_000)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return svlib.canonical_url(v)


class ItemIn(BaseModel):
    url: str
    title: str = Field(min_length=3, max_length=300)
    source: Slug
    source_name: str = Field(min_length=1, max_length=60)
    category: Category
    tags: list[Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,29}$")]] = Field(default_factory=list, max_length=8)
    excerpt: str | None = Field(default=None, max_length=400)
    summary: str | None = Field(default=None, max_length=400)
    author: str | None = Field(default=None, max_length=120)
    published_at: datetime | None = None
    claim_status: ClaimStatus = "reported"
    funding: Funding | None = None
    embed_url: str | None = None   # an X post or YouTube video that is the story itself
    mentions: list[Mention] = Field(default_factory=list, max_length=10)
    score: float = Field(ge=0, le=100)
    score_detail: dict[str, Any] | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return svlib.canonical_url(v)

    @field_validator("title", "excerpt", "summary", "author", "source_name")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = " ".join(v.split())
        if "<" in v and ">" in v:
            raise ValueError("markup is not allowed")
        return v or None

    @field_validator("published_at")
    @classmethod
    def _published(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("published_at needs a timezone")
        if v > datetime.now(timezone.utc) + timedelta(hours=1):
            raise ValueError("published_at is in the future")
        return v

    @field_validator("score_detail")
    @classmethod
    def _detail(cls, v: dict | None) -> dict | None:
        if v is not None and len(repr(v)) > 2000:
            raise ValueError("score_detail is too large")
        return v

    @model_validator(mode="after")
    def _funding_needs_source(self) -> "ItemIn":
        if self.category == "funding" and self.claim_status == "unverified" and self.funding:
            raise ValueError("an unverified funding claim must not carry structured funding data")
        return self


class RunStart(BaseModel):
    feed_date: date
    notes: str | None = Field(default=None, max_length=2000)


class ItemsIn(BaseModel):
    items: list[dict[str, Any]] = Field(max_length=200)   # validated one by one so one bad item never sinks the batch


class SourceStatus(BaseModel):
    source: Slug
    ok: bool
    fetched: int = Field(default=0, ge=0)
    kept: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=300)


class RunFinish(BaseModel):
    status: Literal["complete", "partial", "failed"]
    sources: list[SourceStatus] = Field(default_factory=list, max_length=80)
    errors: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------- read side

ITEM_COLUMNS = """
    i.id, i.url, i.source, i.source_name, i.title, i.excerpt, i.summary, i.author,
    i.published_at, i.discovered_at, i.updated_at, i.category, i.tags, i.claim_status,
    i.funding, i.embed_type, i.embed_ref, i.score
"""


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def _item_json(row: dict, mentions: list[dict] | None = None) -> dict:
    out = {k: _iso(v) for k, v in row.items() if k not in ("embed_type", "embed_ref")}
    out["embed"] = {"type": row["embed_type"], "ref": row["embed_ref"]} if row.get("embed_type") else None
    if mentions is not None:
        out["mentions"] = [{k: _iso(v) for k, v in m.items() if k != "item_id"} for m in mentions]
    return out


def _mentions_for(conn, ids: list[str]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {i: [] for i in ids}
    if ids:
        rows = conn.execute(
            "select item_id, url, source, label, points, comments, observed_at from mentions "
            "where item_id = any(%s) order by coalesce(points, 0) desc, label", (ids,)
        ).fetchall()
        for m in rows:
            by[m["item_id"]].append(m)
    return by


def _public_run(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": str(row["id"]), "status": row["status"], "operator": row["operator"],
        "started_at": _iso(row["started_at"]), "finished_at": _iso(row["finished_at"]),
        "sources": [{k: s.get(k) for k in ("source", "ok", "kept", "error")} for s in row["sources"]],
    }


@app.get("/v1/health")
def health() -> dict:
    with pool.connection() as conn:
        conn.execute("select 1")
    return {"ok": True}


@app.get("/v1/feed", dependencies=[Depends(require_read)])
def feed(
    feed_date: Annotated[date | None, Query(alias="date")] = None,
    category: Category | None = None,
    source: Slug | None = None,
    tag: Annotated[str | None, Query(pattern=r"^[a-z0-9][a-z0-9-]{1,29}$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 60,
    offset: Annotated[int, Query(ge=0, le=5000)] = 0,
) -> dict:
    """One edition. Without a date: the latest edition that has stories."""
    with pool.connection() as conn:
        if feed_date is None:
            row = conn.execute("select max(feed_date) d from feed_entries").fetchone()
            feed_date = row["d"]
        if feed_date is None:
            return {"date": None, "total": 0, "items": [], "facets": {}, "run": None}
        where, args = ["f.feed_date = %s"], [feed_date]
        if category:
            where.append("i.category = %s"); args.append(category)
        if source:
            where.append("i.source = %s"); args.append(source)
        if tag:
            where.append("%s = any(i.tags)"); args.append(tag)
        cond = " and ".join(where)
        total = conn.execute(f"select count(*) n from feed_entries f join items i on i.id = f.item_id where {cond}", args).fetchone()["n"]
        rows = conn.execute(
            f"select {ITEM_COLUMNS}, f.rank from feed_entries f join items i on i.id = f.item_id "
            f"where {cond} order by f.rank, f.score desc limit %s offset %s", [*args, limit, offset]
        ).fetchall()
        mentions = _mentions_for(conn, [r["id"] for r in rows])
        facets = conn.execute(
            "select jsonb_object_agg(k, n) as categories from (select i.category k, count(*) n from feed_entries f "
            "join items i on i.id = f.item_id where f.feed_date = %s group by 1) t", (feed_date,)
        ).fetchone()["categories"] or {}
        sources = conn.execute(
            "select coalesce(jsonb_object_agg(k, jsonb_build_object('name', nm, 'n', n)), '{}') s from ("
            "select i.source k, min(i.source_name) nm, count(*) n from feed_entries f join items i on i.id = f.item_id "
            "where f.feed_date = %s group by 1) t", (feed_date,)
        ).fetchone()["s"]
        run = conn.execute(
            "select * from runs where feed_date = %s and status <> 'running' order by finished_at desc limit 1", (feed_date,)
        ).fetchone()
        neighbours = conn.execute(
            "select (select max(feed_date) from feed_entries where feed_date < %s) prev, "
            "(select min(feed_date) from feed_entries where feed_date > %s) next", (feed_date, feed_date)
        ).fetchone()
    return {
        "date": feed_date.isoformat(), "total": total,
        "items": [_item_json(r, mentions[r["id"]]) | {"rank": r["rank"]} for r in rows],
        "facets": {"categories": facets, "sources": sources},
        "run": _public_run(run),
        "prev": _iso(neighbours["prev"]), "next": _iso(neighbours["next"]),
    }


@app.get("/v1/dates", dependencies=[Depends(require_read)])
def dates(limit: Annotated[int, Query(ge=1, le=1000)] = 400) -> dict:
    with pool.connection() as conn:
        rows = conn.execute(
            "select feed_date, count(*) n, max(i.updated_at) updated from feed_entries f join items i on i.id = f.item_id "
            "group by feed_date order by feed_date desc limit %s", (limit,)
        ).fetchall()
    return {"dates": [{"date": r["feed_date"].isoformat(), "count": r["n"], "updated_at": _iso(r["updated"])} for r in rows]}


@app.get("/v1/items/{item_id}", dependencies=[Depends(require_read)])
def item(item_id: Annotated[str, PathParam(pattern=r"^[a-z2-7]{12}$")]) -> dict:
    with pool.connection() as conn:
        row = conn.execute(
            f"select {ITEM_COLUMNS}, i.score_detail, f.feed_date, f.rank from items i "
            "left join feed_entries f on f.item_id = i.id where i.id = %s", (item_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "no such item")
        mentions = _mentions_for(conn, [item_id])[item_id]
        related = conn.execute(
            f"select {ITEM_COLUMNS}, f.feed_date from items i join feed_entries f on f.item_id = i.id "
            "where i.id <> %s and (i.tags && %s or (i.funding->>'company') = %s) "
            "order by cardinality(array(select unnest(i.tags) intersect select unnest(%s::text[]))) desc, "
            "f.feed_date desc, i.score desc limit 6",
            (item_id, row["tags"] or ["-"], (row["funding"] or {}).get("company"), row["tags"] or []),
        ).fetchall()
    out = _item_json(row, mentions)
    out["related"] = [_item_json(r) for r in related]
    return out


@app.get("/v1/topics", dependencies=[Depends(require_read)])
def topics() -> dict:
    with pool.connection() as conn:
        rows = conn.execute(
            "select t tag, count(*) n, max(f.feed_date) latest from items i join feed_entries f on f.item_id = i.id, "
            "unnest(i.tags) t group by t order by n desc, t"
        ).fetchall()
    return {"topics": [{"tag": r["tag"], "count": r["n"], "latest": _iso(r["latest"])} for r in rows]}


@app.get("/v1/topics/{tag}", dependencies=[Depends(require_read)])
def topic(
    tag: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 40,
    offset: Annotated[int, Query(ge=0, le=5000)] = 0,
) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,29}", tag):
        raise HTTPException(404, "no such topic")
    with pool.connection() as conn:
        total = conn.execute(
            "select count(*) n from items i join feed_entries f on f.item_id = i.id where %s = any(i.tags)", (tag,)
        ).fetchone()["n"]
        rows = conn.execute(
            f"select {ITEM_COLUMNS}, f.feed_date from items i join feed_entries f on f.item_id = i.id "
            "where %s = any(i.tags) order by f.feed_date desc, f.rank limit %s offset %s", (tag, limit, offset)
        ).fetchall()
        mentions = _mentions_for(conn, [r["id"] for r in rows])
    return {"tag": tag, "total": total, "items": [_item_json(r, mentions[r["id"]]) for r in rows]}


@app.get("/v1/search", dependencies=[Depends(require_read)])
def search(
    q: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
    offset: Annotated[int, Query(ge=0, le=1000)] = 0,
) -> dict:
    with pool.connection() as conn:
        rows = conn.execute(
            f"select {ITEM_COLUMNS}, f.feed_date, ts_rank(i.search, websearch_to_tsquery('english', %s)) r, "
            "count(*) over () total from items i join feed_entries f on f.item_id = i.id "
            "where i.search @@ websearch_to_tsquery('english', %s) or lower(%s) = any(i.tags) "
            "order by r desc, f.feed_date desc limit %s offset %s", (q, q, q, limit, offset)
        ).fetchall()
    total = rows[0]["total"] if rows else 0
    return {"q": q, "total": total, "items": [_item_json({k: v for k, v in r.items() if k not in ("r", "total")}) for r in rows]}


@app.get("/v1/sitemap", dependencies=[Depends(require_read)])
def sitemap() -> dict:
    with pool.connection() as conn:
        items = conn.execute(
            "select i.id, i.title, i.updated_at, f.feed_date from items i join feed_entries f on f.item_id = i.id "
            "order by f.feed_date desc, f.rank limit 45000"
        ).fetchall()
    return {"items": [{"id": r["id"], "title": r["title"], "updated_at": _iso(r["updated_at"]), "date": _iso(r["feed_date"])} for r in items]}


# ---------------------------------------------------------------- ingest side

@app.post("/v1/ingest/runs")
def start_run(body: RunStart, operator: Annotated[str, Depends(require_ingest)]) -> dict:
    today = svlib.today_pt()
    if not FIRST_EDITION <= body.feed_date <= today:
        raise HTTPException(422, f"feed_date must be between {FIRST_EDITION} and today in Pacific time ({today})")
    run_id = uuid.uuid4()
    with pool.connection() as conn:
        conn.execute(
            "update runs set status = 'failed', finished_at = now(), "
            "errors = errors || '[\"interrupted: no finish within 3 hours\"]'::jsonb "
            "where status = 'running' and started_at < now() - %s", (STALE_RUN,)
        )
        conn.execute("insert into runs (id, feed_date, operator, notes) values (%s, %s, %s, %s)",
                     (run_id, body.feed_date, operator, body.notes))
    return {"run_id": str(run_id), "feed_date": body.feed_date.isoformat(), "operator": operator}


def _open_run(conn, run_id: uuid.UUID) -> dict:
    run = conn.execute("select * from runs where id = %s", (run_id,)).fetchone()
    if not run:
        raise HTTPException(404, "no such run")
    if run["status"] != "running":
        raise HTTPException(409, f"run is already {run['status']}")
    return run


def _find_near_duplicate(conn, it: ItemIn, new_id: str) -> str | None:
    """An existing item that is the same story under another URL: the same
    normalized headline, or a near-identical one, within three days."""
    around = it.published_at or datetime.now(timezone.utc)
    rows = conn.execute(
        "select id, title from items where id <> %s and coalesce(published_at, discovered_at) between %s and %s "
        "order by discovered_at desc limit 3000",
        (new_id, around - timedelta(days=3), around + timedelta(days=3)),
    ).fetchall()
    for r in rows:
        if svlib.similar_titles(r["title"], it.title):
            return r["id"]
    return None


def _merge_into(conn, target: str, it: ItemIn) -> None:
    """The story is already stored under `target`: keep its title and source,
    record this sighting as a mention, widen its tags, keep the higher score."""
    it.mentions.insert(0, Mention(url=it.url, source=it.source, label=it.source_name))
    conn.execute(
        "update items set tags = (select array(select distinct t from unnest(tags || %s::text[]) t limit 8)), "
        "score = greatest(score, %s), updated_at = now() where id = %s", (it.tags, it.score, target))


def _upsert(conn, item_id_: str, it: ItemIn) -> None:
    embed = (svlib.detect_embed(it.embed_url) if it.embed_url else None) or svlib.detect_embed(it.url)
    conn.execute(
        """insert into items (id, url, dedupe_key, source, source_name, title, excerpt, summary, author,
               published_at, category, tags, claim_status, funding, embed_type, embed_ref, score, score_detail)
           values (%(id)s, %(url)s, %(key)s, %(source)s, %(source_name)s, %(title)s, %(excerpt)s, %(summary)s,
               %(author)s, %(published_at)s, %(category)s, %(tags)s, %(claim_status)s, %(funding)s,
               %(embed_type)s, %(embed_ref)s, %(score)s, %(score_detail)s)
           on conflict (id) do update set
               url = excluded.url, title = excluded.title, source_name = excluded.source_name,
               dedupe_key = excluded.dedupe_key,
               excerpt = coalesce(excluded.excerpt, items.excerpt),
               summary = coalesce(excluded.summary, items.summary),
               author = coalesce(excluded.author, items.author),
               published_at = coalesce(items.published_at, excluded.published_at),
               category = excluded.category, tags = excluded.tags, claim_status = excluded.claim_status,
               funding = coalesce(excluded.funding, items.funding),
               embed_type = coalesce(excluded.embed_type, items.embed_type),
               embed_ref = coalesce(excluded.embed_ref, items.embed_ref),
               score = excluded.score, score_detail = excluded.score_detail, updated_at = now()""",
        {
            "id": item_id_, "url": it.url, "key": svlib.dedupe_key(it.title), "source": it.source,
            "source_name": it.source_name, "title": it.title, "excerpt": it.excerpt, "summary": it.summary,
            "author": it.author, "published_at": it.published_at, "category": it.category,
            "tags": list(dict.fromkeys(it.tags)), "claim_status": it.claim_status,
            "funding": Jsonb(it.funding.model_dump(exclude_none=True)) if it.funding else None,
            "embed_type": embed[0] if embed else None, "embed_ref": embed[1] if embed else None,
            "score": it.score, "score_detail": Jsonb(it.score_detail) if it.score_detail else None,
        },
    )


def _ingest_one(conn, run: dict, it: ItemIn) -> dict:
    new_id = svlib.item_id(it.url)
    existing = conn.execute("select id, source from items where id = %s", (new_id,)).fetchone()
    if existing and existing["source"] == it.source:
        target, outcome = new_id, "updated"          # the same channel again: a rerun refreshes it
        _upsert(conn, target, it)
    elif existing:
        target, outcome = new_id, "merged"           # same URL found through another channel
        _merge_into(conn, target, it)
    elif dup := _find_near_duplicate(conn, it, new_id):
        target, outcome = dup, "merged"              # same story under another URL
        _merge_into(conn, target, it)
    else:
        target, outcome = new_id, "inserted"
        _upsert(conn, target, it)

    target_url = conn.execute("select url from items where id = %s", (target,)).fetchone()["url"]
    for m in it.mentions:
        if m.url == target_url:
            continue
        conn.execute(
            "insert into mentions (item_id, url, source, label, points, comments) values (%s, %s, %s, %s, %s, %s) "
            "on conflict (item_id, url) do update set points = coalesce(excluded.points, mentions.points), "
            "comments = coalesce(excluded.comments, mentions.comments), label = excluded.label, observed_at = now()",
            (target, m.url, m.source, m.label, m.points, m.comments),
        )
    featured = conn.execute("select feed_date from feed_entries where item_id = %s", (target,)).fetchone()
    if featured and featured["feed_date"] != run["feed_date"]:
        return {"id": target, "outcome": outcome, "edition": featured["feed_date"].isoformat(), "note": "already in another edition"}
    conn.execute(
        "insert into feed_entries (feed_date, item_id, score, run_id) values (%s, %s, %s, %s) "
        "on conflict (feed_date, item_id) do update set score = greatest(feed_entries.score, excluded.score), run_id = excluded.run_id",
        (run["feed_date"], target, it.score, run["id"]),
    )
    return {"id": target, "outcome": outcome, "edition": run["feed_date"].isoformat()}


@app.post("/v1/ingest/runs/{run_id}/items")
def ingest_items(run_id: uuid.UUID, body: ItemsIn, operator: Annotated[str, Depends(require_ingest)]) -> dict:
    results, counts = [], {"inserted": 0, "updated": 0, "merged": 0, "rejected": 0}
    with pool.connection() as conn:
        run = _open_run(conn, run_id)
        for index, raw in enumerate(body.items):
            try:
                it = ItemIn.model_validate(raw)
            except Exception as exc:  # pydantic ValidationError or a URL ValueError
                counts["rejected"] += 1
                results.append({"index": index, "outcome": "rejected", "reason": str(exc)[:300]})
                continue
            try:
                with conn.transaction():
                    res = _ingest_one(conn, run, it)
            except Exception as exc:
                counts["rejected"] += 1
                results.append({"index": index, "outcome": "rejected", "reason": f"database: {exc}"[:300]})
                continue
            counts[res["outcome"]] += 1
            results.append({"index": index, **res})
        conn.execute(
            "update runs set items_received = items_received + %s, items_inserted = items_inserted + %s, "
            "items_updated = items_updated + %s, items_merged = items_merged + %s, items_rejected = items_rejected + %s "
            "where id = %s",
            (len(body.items), counts["inserted"], counts["updated"], counts["merged"], counts["rejected"], run_id),
        )
    return {"run_id": str(run_id), **counts, "results": results}


@app.post("/v1/ingest/runs/{run_id}/finish")
def finish_run(run_id: uuid.UUID, body: RunFinish, operator: Annotated[str, Depends(require_ingest)]) -> dict:
    status = body.status
    if status == "complete" and any(not s.ok for s in body.sources):
        status = "partial"   # a run with a failed source is never reported as complete
    with pool.connection() as conn:
        run = _open_run(conn, run_id)
        conn.execute(
            "update feed_entries f set rank = r.rn from (select item_id, row_number() over "
            "(order by score desc, added_at) rn from feed_entries where feed_date = %s) r "
            "where f.feed_date = %s and f.item_id = r.item_id", (run["feed_date"], run["feed_date"]),
        )
        conn.execute(
            "update runs set status = %s, finished_at = now(), sources = %s, errors = errors || %s, "
            "notes = coalesce(%s, notes) where id = %s",
            (status, Jsonb([s.model_dump() for s in body.sources]), Jsonb(body.errors), body.notes, run_id),
        )
        row = conn.execute("select * from runs where id = %s", (run_id,)).fetchone()
        n = conn.execute("select count(*) n from feed_entries where feed_date = %s", (run["feed_date"],)).fetchone()["n"]
    return {**{k: _iso(v) for k, v in row.items() if k != "id"}, "id": str(row["id"]), "edition_items": n}


@app.get("/v1/ingest/runs/{run_id}")
def get_run(run_id: uuid.UUID, operator: Annotated[str, Depends(require_ingest)]) -> dict:
    with pool.connection() as conn:
        row = conn.execute("select * from runs where id = %s", (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, "no such run")
        n = conn.execute("select count(*) n from feed_entries where feed_date = %s", (row["feed_date"],)).fetchone()["n"]
    return {**{k: _iso(v) for k, v in row.items() if k != "id"}, "id": str(row["id"]), "edition_items": n}


@app.get("/v1/ingest/editions/{feed_date}")
def edition_ids(feed_date: date, operator: Annotated[str, Depends(require_ingest)]) -> dict:
    """What is persisted for an edition, so a run can verify its own writes."""
    with pool.connection() as conn:
        rows = conn.execute(
            "select f.item_id, f.rank, i.url, i.title from feed_entries f join items i on i.id = f.item_id "
            "where f.feed_date = %s order by f.rank", (feed_date,)
        ).fetchall()
        runs = conn.execute(
            "select id, status, operator, started_at, finished_at, items_received, items_inserted, items_updated, "
            "items_merged, items_rejected from runs where feed_date = %s order by started_at", (feed_date,)
        ).fetchall()
    return {
        "date": feed_date.isoformat(),
        "items": [dict(r) for r in rows],
        "runs": [{k: (str(v) if k == "id" else _iso(v)) for k, v in r.items()} for r in runs],
    }
