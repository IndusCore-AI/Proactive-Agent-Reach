"""Keeping Up with Silicon Valley: read + ingest API over the induscore_sv
database. Runs on the prod VM on 127.0.0.1 only; the public site reaches it
through its own Cloudflare quick tunnel (see ../ops).

Three kinds of caller, three kinds of token:
  read     the Vercel server (SV_READ_TOKEN_SHA256 in the env file)
  private  the Vercel server, only for a founders-unlocked page: the founders'
           own take on each mover (SV_PRIVATE_READ_TOKEN_SHA256, a different token)
  ingest   a founder's Claude Code run (rows in ingest_tokens, one per person)
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

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Query, Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "aggregate-silicon-valley" / "scripts"))
import svlib  # noqa: E402  (the one copy of the URL / duplicate rules, shared with the skill)

DATABASE_URL = os.environ.get("SV_DATABASE_URL", "postgresql:///induscore_sv")
READ_TOKEN_SHA256 = os.environ.get("SV_READ_TOKEN_SHA256", "")
PRIVATE_TOKEN_SHA256 = os.environ.get("SV_PRIVATE_READ_TOKEN_SHA256", "")
FIRST_EDITION = date(2026, 1, 1)
STALE_RUN = timedelta(hours=3)

Category = Literal["funding", "acquisition", "launch", "news", "discussion", "analysis"]
ClaimStatus = Literal["confirmed", "reported", "unverified", "opinion"]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")]
Tag = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,29}$")]
MOVER_ID = r"^[a-z0-9][a-z0-9-]{1,59}$"
# Site paths under /movers/ that a mover id must never shadow.
RESERVED_MOVER_IDS = {"unlock", "lock"}
MoverKind = Literal["company", "app", "skill"]
MoverClaim = Literal["confirmed", "reported", "unverified"]

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


def require_private(authorization: Annotated[str | None, Header()] = None) -> None:
    """The founders' take. Its own token: the read token never opens it, and a
    deployment where both tokens are the same is refused outright."""
    token = _bearer(authorization)
    if (
        not PRIVATE_TOKEN_SHA256
        or hmac.compare_digest(PRIVATE_TOKEN_SHA256, READ_TOKEN_SHA256)
        or not hmac.compare_digest(_sha256(token), PRIVATE_TOKEN_SHA256)
    ):
        raise HTTPException(403, "invalid private read token")


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

def _one_line(v: str | None) -> str | None:
    """Collapse whitespace; refuse markup. Used for every public text field."""
    if v is None:
        return None
    v = " ".join(v.split())
    if "<" in v and ">" in v:
        raise ValueError("markup is not allowed")
    return v or None


def _https_image(v: str | None) -> str | None:
    """A link to the publisher's own image: plain https, public host. The
    original string is kept (CDNs need their query)."""
    if v is None:
        return None
    v = v.strip()
    if not v.startswith("https://") or any(c.isspace() for c in v) or any(c in v for c in "<>\"'"):
        raise ValueError("image_url must be a plain https URL")
    svlib.canonical_url(v)  # same public-host rules as story URLs
    return v


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
    tags: list[Tag] = Field(default_factory=list, max_length=8)
    excerpt: str | None = Field(default=None, max_length=400)
    summary: str | None = Field(default=None, max_length=400)
    author: str | None = Field(default=None, max_length=120)
    published_at: datetime | None = None
    claim_status: ClaimStatus = "reported"
    funding: Funding | None = None
    embed_url: str | None = None   # an X post or YouTube video: the story itself, or one the source embedded
    image_url: str | None = Field(default=None, max_length=1000)   # link to the publisher's own image
    image_kind: Literal["cover", "logo"] | None = None
    mentions: list[Mention] = Field(default_factory=list, max_length=10)
    score: float = Field(ge=0, le=100)
    score_detail: dict[str, Any] | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return svlib.canonical_url(v)

    @field_validator("image_url")
    @classmethod
    def _image(cls, v: str | None) -> str | None:
        return _https_image(v)

    @field_validator("title", "excerpt", "summary", "author", "source_name")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _one_line(v)

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
    name: str | None = Field(default=None, max_length=60)
    ok: bool
    fetched: int = Field(default=0, ge=0)
    kept: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=300)


class RunFinish(BaseModel):
    status: Literal["complete", "partial", "failed"]
    sources: list[SourceStatus] = Field(default_factory=list, max_length=80)
    errors: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class Traction(BaseModel):
    """One traction fact, as its source states it, with the date it was true."""
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=120)      # "Paying customers"
    value: str = Field(min_length=1, max_length=120)      # "1,200"
    source_url: str                                       # required: no source, no line
    as_of: date

    @field_validator("label", "value")
    @classmethod
    def _clean(cls, v: str) -> str:
        out = _one_line(v)
        if not out:
            raise ValueError("must not be blank")
        return out

    @field_validator("source_url")
    @classmethod
    def _source(cls, v: str) -> str:
        url = svlib.canonical_url(v)
        if not url.startswith("https://"):
            raise ValueError("source_url must be an https URL")
        return url

    @field_validator("as_of")
    @classmethod
    def _as_of(cls, v: date) -> date:
        if v > svlib.today_pt() + timedelta(days=1):
            raise ValueError("as_of is in the future")
        return v


class MoverNotes(BaseModel):
    """The founders' private take. Fields left out are kept as they are;
    a field sent as null is cleared."""
    model_config = ConfigDict(extra="forbid")
    take: str | None = Field(default=None, max_length=1500)       # how it helps us
    learn: str | None = Field(default=None, max_length=1000)      # what to learn
    localize: str | None = Field(default=None, max_length=1000)   # where to localize

    @field_validator("take", "learn", "localize")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        lines = [" ".join(line.split()) for line in v.replace("\r\n", "\n").split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


class MoverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Annotated[str, Field(pattern=MOVER_ID)]
    name: str = Field(min_length=1, max_length=120)
    kind: MoverKind
    url: str
    one_liner: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=800)
    traction: list[Traction] = Field(default_factory=list, max_length=8)
    markets_live: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(default_factory=list, max_length=8)
    claim_status: MoverClaim = "reported"
    tags: list[Tag] = Field(default_factory=list, max_length=8)
    image_url: str | None = Field(default=None, max_length=1000)
    image_kind: Literal["cover", "logo"] | None = None
    status: Literal["watching", "archived"] | None = None   # omitted: new movers watch, existing ones keep theirs
    notes: MoverNotes | None = None
    item_urls: list[Annotated[str, Field(max_length=2048)]] = Field(default_factory=list, max_length=50)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if v in RESERVED_MOVER_IDS:
            raise ValueError(f"id {v!r} is reserved")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return svlib.canonical_url(v)

    @field_validator("image_url")
    @classmethod
    def _image(cls, v: str | None) -> str | None:
        return _https_image(v)

    @field_validator("name", "one_liner", "summary")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _one_line(v)

    @field_validator("name", "one_liner")
    @classmethod
    def _required(cls, v: str | None) -> str:
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("markets_live")
    @classmethod
    def _markets(cls, v: list[str]) -> list[str]:
        out = [m for m in (_one_line(x) for x in v) if m]
        return list(dict.fromkeys(out))


class MoversIn(BaseModel):
    movers: list[dict[str, Any]] = Field(max_length=50)   # validated one by one, like items


class LinkIn(BaseModel):
    item_urls: list[Annotated[str, Field(max_length=2048)]] = Field(min_length=1, max_length=50)


# ---------------------------------------------------------------- read side

ITEM_COLUMNS = """
    i.id, i.url, i.source, i.source_name, i.title, i.excerpt, i.summary, i.author,
    i.published_at, i.discovered_at, i.updated_at, i.category, i.tags, i.claim_status,
    i.funding, i.embed_type, i.embed_ref, i.score, i.image_url, i.image_kind
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
        "id": str(row["id"]), "status": row["status"],
        "started_at": _iso(row["started_at"]), "finished_at": _iso(row["finished_at"]),
        "sources": [{k: s.get(k) for k in ("source", "name", "ok", "fetched", "kept", "error")} for s in row["sources"]],
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
        movers = conn.execute(
            "select m.id, m.name, m.kind from mover_items mi join movers m on m.id = mi.mover_id "
            "where mi.item_id = %s and m.status = 'watching' order by m.name", (item_id,)
        ).fetchall()
    out = _item_json(row, mentions)
    out["related"] = [_item_json(r) for r in related]
    out["movers"] = [{"id": m["id"], "name": m["name"], "kind": m["kind"]} for m in movers]
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
        movers = conn.execute(
            "select m.id, greatest(m.updated_at, max(mi.added_at)) updated_at from movers m "
            "left join mover_items mi on mi.mover_id = m.id where m.status = 'watching' group by m.id order by m.id"
        ).fetchall()
    return {
        "items": [{"id": r["id"], "title": r["title"], "updated_at": _iso(r["updated_at"]), "date": _iso(r["feed_date"])} for r in items],
        "movers": [{"id": r["id"], "updated_at": _iso(r["updated_at"])} for r in movers],
    }


# Public mover facts. The column list is explicit on purpose: the founders'
# take is in mover_notes and never joined here; who added a mover stays out too.
MOVER_COLUMNS = """
    m.id, m.name, m.kind, m.url, m.one_liner, m.summary, m.traction, m.markets_live, m.claim_status,
    m.tags, m.image_url, m.image_kind, m.first_added_at, m.updated_at
"""
MOVER_NEWS = """
    left join lateral (
        select count(*) news_count, max(coalesce(i.published_at, i.discovered_at)) latest_news_at
        from mover_items mi join items i on i.id = mi.item_id where mi.mover_id = m.id
    ) n on true
"""


def _mover_json(row: dict) -> dict:
    return {k: _iso(v) for k, v in row.items()}


@app.get("/v1/movers", dependencies=[Depends(require_read)])
def movers(
    kind: MoverKind | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 60,
    offset: Annotated[int, Query(ge=0, le=5000)] = 0,
) -> dict:
    """Movers being watched, most recently active first, with how many stories feed each."""
    where, args = ["m.status = 'watching'"], []
    if kind:
        where.append("m.kind = %s"); args.append(kind)
    cond = " and ".join(where)
    with pool.connection() as conn:
        total = conn.execute(f"select count(*) n from movers m where {cond}", args).fetchone()["n"]
        rows = conn.execute(
            f"select {MOVER_COLUMNS}, n.news_count, n.latest_news_at from movers m {MOVER_NEWS} where {cond} "
            "order by greatest(m.updated_at, n.latest_news_at) desc, m.name limit %s offset %s", [*args, limit, offset]
        ).fetchall()
        kinds = conn.execute(
            "select coalesce(jsonb_object_agg(kind, n), '{}') k from (select kind, count(*) n from movers "
            "where status = 'watching' group by kind) t"
        ).fetchone()["k"]
    return {"total": total, "movers": [_mover_json(r) for r in rows], "facets": {"kinds": kinds}}


@app.get("/v1/movers/{mover_id}", dependencies=[Depends(require_read)])
def mover(mover_id: Annotated[str, PathParam(pattern=MOVER_ID)]) -> dict:
    with pool.connection() as conn:
        row = conn.execute(
            f"select {MOVER_COLUMNS}, n.news_count, n.latest_news_at from movers m {MOVER_NEWS} "
            "where m.id = %s and m.status = 'watching'", (mover_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "no such mover")
        items = conn.execute(
            f"select {ITEM_COLUMNS}, f.feed_date from mover_items mi join items i on i.id = mi.item_id "
            "left join feed_entries f on f.item_id = i.id where mi.mover_id = %s "
            "order by coalesce(i.published_at, i.discovered_at) desc limit 20", (mover_id,)
        ).fetchall()
        mentions = _mentions_for(conn, [r["id"] for r in items])
    return _mover_json(row) | {"items": [_item_json(r, mentions[r["id"]]) for r in items]}


# ---------------------------------------------------------------- private side

@app.get("/v1/private/movers", dependencies=[Depends(require_private)])
def private_movers(response: Response, ids: Annotated[str | None, Query(max_length=6200)] = None) -> dict:
    """The founders' take, keyed by mover id. Only a founders-unlocked page asks."""
    response.headers["Cache-Control"] = "no-store"
    wanted: list[str] | None = None
    if ids is not None:
        wanted = [x for x in ids.split(",") if x]
        if len(wanted) > 100 or not all(re.fullmatch(MOVER_ID, x) for x in wanted):
            raise HTTPException(422, "ids must be at most 100 comma-separated mover ids")
    with pool.connection() as conn:
        rows = conn.execute(
            "select mover_id, take, learn, localize, updated_at from mover_notes"
            + (" where mover_id = any(%s)" if wanted is not None else "") + " order by mover_id",
            (wanted,) if wanted is not None else (),
        ).fetchall()
    return {r["mover_id"]: {"take": r["take"], "learn": r["learn"], "localize": r["localize"],
                            "updated_at": _iso(r["updated_at"])} for r in rows}


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
        "score = greatest(score, %s), image_url = coalesce(image_url, %s), "
        "image_kind = case when image_url is null then %s else image_kind end, updated_at = now() where id = %s",
        (it.tags, it.score, it.image_url, it.image_kind if it.image_url else None, target))
    embed = (svlib.detect_embed(it.embed_url) if it.embed_url else None) or svlib.detect_embed(it.url)
    if embed:
        conn.execute(
            "update items set embed_ref = case when embed_type is null then %s else embed_ref end, "
            "embed_type = coalesce(embed_type, %s) where id = %s", (embed[1], embed[0], target))


def _upsert(conn, item_id_: str, it: ItemIn) -> None:
    embed = (svlib.detect_embed(it.embed_url) if it.embed_url else None) or svlib.detect_embed(it.url)
    conn.execute(
        """insert into items (id, url, dedupe_key, source, source_name, title, excerpt, summary, author,
               published_at, category, tags, claim_status, funding, embed_type, embed_ref, score, score_detail,
               image_url, image_kind)
           values (%(id)s, %(url)s, %(key)s, %(source)s, %(source_name)s, %(title)s, %(excerpt)s, %(summary)s,
               %(author)s, %(published_at)s, %(category)s, %(tags)s, %(claim_status)s, %(funding)s,
               %(embed_type)s, %(embed_ref)s, %(score)s, %(score_detail)s, %(image_url)s, %(image_kind)s)
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
               image_url = coalesce(excluded.image_url, items.image_url),
               image_kind = case when excluded.image_url is not null then excluded.image_kind else items.image_kind end,
               score = excluded.score, score_detail = excluded.score_detail, updated_at = now()""",
        {
            "id": item_id_, "url": it.url, "key": svlib.dedupe_key(it.title), "source": it.source,
            "source_name": it.source_name, "title": it.title, "excerpt": it.excerpt, "summary": it.summary,
            "author": it.author, "published_at": it.published_at, "category": it.category,
            "tags": list(dict.fromkeys(it.tags)), "claim_status": it.claim_status,
            "funding": Jsonb(it.funding.model_dump(exclude_none=True)) if it.funding else None,
            "embed_type": embed[0] if embed else None, "embed_ref": embed[1] if embed else None,
            "score": it.score, "score_detail": Jsonb(it.score_detail) if it.score_detail else None,
            "image_url": it.image_url, "image_kind": it.image_kind if it.image_url else None,
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


# ---------------------------------------------------------------- movers (ingest)
#
# Movers are added only when a founder asks; no run is involved. Each write
# records the operator. Notes go to mover_notes and nowhere else.

def _resolve_items(conn, urls: list[str]) -> tuple[list[str], list[str]]:
    """Item ids for story URLs that exist (as an item, or as a recorded
    sighting of one); the URLs that match nothing are returned as missing."""
    found: list[str] = []
    missing: list[str] = []
    for raw in urls:
        try:
            url = svlib.canonical_url(raw)
        except ValueError:
            missing.append(raw[:300])
            continue
        row = conn.execute(
            "(select id, 0 p from items where id = %s or url = %s) "
            "union all (select item_id, 1 from mentions where url = %s) order by p limit 1",
            (svlib.item_id(url), url, url),
        ).fetchone()
        if row:
            found.append(row["id"])
        else:
            missing.append(url)
    return list(dict.fromkeys(found)), missing


def _link(conn, mover_id: str, item_ids: list[str]) -> int:
    for iid in item_ids:
        conn.execute("insert into mover_items (mover_id, item_id) values (%s, %s) on conflict do nothing", (mover_id, iid))
    return len(item_ids)


def _upsert_mover(conn, m: MoverIn, operator: str) -> bool:
    """Insert or replace a mover's public facts; True when it is new."""
    row = conn.execute(
        """insert into movers (id, name, kind, url, one_liner, summary, traction, markets_live, claim_status, tags,
               image_url, image_kind, status, added_by, updated_by)
           values (%(id)s, %(name)s, %(kind)s, %(url)s, %(one_liner)s, %(summary)s, %(traction)s, %(markets)s,
               %(claim)s, %(tags)s, %(image_url)s, %(image_kind)s, coalesce(%(status)s, 'watching'), %(op)s, %(op)s)
           on conflict (id) do update set
               name = excluded.name, kind = excluded.kind, url = excluded.url, one_liner = excluded.one_liner,
               summary = excluded.summary, traction = excluded.traction, markets_live = excluded.markets_live,
               claim_status = excluded.claim_status, tags = excluded.tags, image_url = excluded.image_url,
               image_kind = excluded.image_kind, status = coalesce(%(status)s, movers.status),
               updated_by = excluded.updated_by, updated_at = now()
           returning (xmax = 0) as inserted""",
        {
            "id": m.id, "name": m.name, "kind": m.kind, "url": m.url, "one_liner": m.one_liner, "summary": m.summary,
            "traction": Jsonb([t.model_dump(mode="json") for t in m.traction]), "markets": m.markets_live,
            "claim": m.claim_status, "tags": list(dict.fromkeys(m.tags)), "image_url": m.image_url,
            "image_kind": m.image_kind if m.image_url else None, "status": m.status, "op": operator,
        },
    ).fetchone()
    if m.notes is not None and m.notes.model_fields_set:
        fields = sorted(m.notes.model_fields_set)          # a subset of take / learn / localize (extra fields are refused)
        cols = ", ".join(fields)
        conn.execute(
            f"insert into mover_notes (mover_id, {cols}, updated_by) values (%s, {', '.join(['%s'] * len(fields))}, %s) "
            f"on conflict (mover_id) do update set {', '.join(f'{f} = excluded.{f}' for f in fields)}, "
            "updated_by = excluded.updated_by, updated_at = now()",
            (m.id, *[getattr(m.notes, f) for f in fields], operator),
        )
    return bool(row["inserted"])


def _mover_exists(conn, mover_id: str) -> None:
    if not conn.execute("select 1 from movers where id = %s", (mover_id,)).fetchone():
        raise HTTPException(404, "no such mover")


@app.post("/v1/ingest/movers")
def ingest_movers(body: MoversIn, operator: Annotated[str, Depends(require_ingest)]) -> dict:
    results, counts = [], {"inserted": 0, "updated": 0, "rejected": 0}
    with pool.connection() as conn:
        for index, raw in enumerate(body.movers):
            try:
                m = MoverIn.model_validate(raw)
            except Exception as exc:  # pydantic ValidationError or a URL ValueError
                counts["rejected"] += 1
                results.append({"index": index, "id": raw.get("id") if isinstance(raw.get("id"), str) else None,
                                "outcome": "rejected", "reason": str(exc)[:500]})
                continue
            try:
                with conn.transaction():
                    inserted = _upsert_mover(conn, m, operator)
                    ids, missing = _resolve_items(conn, m.item_urls)
                    linked = _link(conn, m.id, ids)
            except Exception as exc:
                counts["rejected"] += 1
                results.append({"index": index, "id": m.id, "outcome": "rejected", "reason": f"database: {exc}"[:300]})
                continue
            outcome = "inserted" if inserted else "updated"
            counts[outcome] += 1
            results.append({"index": index, "id": m.id, "outcome": outcome, "linked": linked, "missing": missing,
                            "notes": bool(m.notes and m.notes.model_fields_set)})
    return {"operator": operator, **counts, "results": results}


@app.get("/v1/ingest/movers")
def ingest_mover_list(operator: Annotated[str, Depends(require_ingest)]) -> dict:
    """Every mover (watching or archived), so a run can match stories to them."""
    with pool.connection() as conn:
        rows = conn.execute("select id, name, kind, url, status from movers order by name").fetchall()
    return {"movers": [dict(r) for r in rows]}


@app.post("/v1/ingest/movers/{mover_id}/link")
def link_mover(mover_id: Annotated[str, PathParam(pattern=MOVER_ID)], body: LinkIn,
               operator: Annotated[str, Depends(require_ingest)]) -> dict:
    with pool.connection() as conn:
        _mover_exists(conn, mover_id)
        ids, missing = _resolve_items(conn, body.item_urls)
        linked = _link(conn, mover_id, ids)
    return {"id": mover_id, "linked": linked, "missing": missing}


@app.post("/v1/ingest/movers/{mover_id}/archive")
def archive_mover(mover_id: Annotated[str, PathParam(pattern=MOVER_ID)],
                  operator: Annotated[str, Depends(require_ingest)]) -> dict:
    with pool.connection() as conn:
        _mover_exists(conn, mover_id)
        conn.execute("update movers set status = 'archived', updated_by = %s, updated_at = now() where id = %s",
                     (operator, mover_id))
    return {"id": mover_id, "status": "archived"}
