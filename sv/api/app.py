"""Keeping Up with Silicon Valley: read + ingest API over the induscore_sv
database. Runs on the prod VM on 127.0.0.1 only; the public site reaches it
through its own Cloudflare quick tunnel (see ../ops).

Three kinds of caller, three kinds of token:
  read      the Vercel server (SV_READ_TOKEN_SHA256 in the env file)
  founders  the Vercel server, only for a founders-unlocked page: the founders'
            desk (their take, scores, votes, stages, proposed movers), their
            research, and the votes, stage changes and publishing they do there
            (SV_FOUNDERS_TOKEN_SHA256, a different token)
  ingest    a founder's Claude Code run (rows in ingest_tokens, one per person)
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
FOUNDERS_TOKEN_SHA256 = os.environ.get("SV_FOUNDERS_TOKEN_SHA256", "")
FIRST_EDITION = date(2026, 1, 1)
STALE_RUN = timedelta(hours=3)

Category = Literal["funding", "acquisition", "launch", "news", "discussion", "analysis"]
ClaimStatus = Literal["confirmed", "reported", "unverified", "opinion"]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")]
Tag = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,29}$")]
MOVER_ID = r"^[a-z0-9][a-z0-9-]{1,59}$"
# Site paths under /movers/ that a mover id must never shadow.
RESERVED_MOVER_IDS = {"unlock", "lock", "updates", "research"}
MoverKind = Literal["company", "app", "skill"]
MoverClaim = Literal["confirmed", "reported", "unverified"]
MoverStatus = Literal["proposed", "watching", "archived"]
MoverStage = Literal["new", "researching", "building", "passed"]
Founder = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")]
# The office-hours rubric (teamctx k:878): line -> maximum points; 100 in all.
RUBRIC = {"demand": 25, "problem": 10, "fit": 15, "wedge": 10, "market": 10, "future": 15, "moat": 10, "whitespace": 5}
# The rubric's first band: an idea under it stays off the list.
RESEARCH_CUTOFF = 40
ResearchOutcome = Literal["makes_list", "below_cutoff", "no", "replaced", "input"]
TRENDING_WINDOW = "14 days"

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


def require_founders(authorization: Annotated[str | None, Header()] = None) -> None:
    """The founders' desk. Its own token: the read token never opens it, and a
    deployment where both tokens are the same is refused outright."""
    token = _bearer(authorization)
    if (
        not FOUNDERS_TOKEN_SHA256
        or hmac.compare_digest(FOUNDERS_TOKEN_SHA256, READ_TOKEN_SHA256)
        or not hmac.compare_digest(_sha256(token), FOUNDERS_TOKEN_SHA256)
    ):
        raise HTTPException(403, "invalid founders token")


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


def _rubric_lines(v: dict[str, int]) -> dict[str, int]:
    if set(v) != set(RUBRIC):
        raise ValueError(f"lines must be exactly {', '.join(RUBRIC)}")
    for k, n in v.items():
        if not 0 <= n <= RUBRIC[k]:
            raise ValueError(f"{k} must be between 0 and {RUBRIC[k]}")
    return {k: v[k] for k in RUBRIC}


class Score(BaseModel):
    """The office-hours rubric for the localized idea (not the original
    product), for one named market. The total is always the sum of the lines."""
    model_config = ConfigDict(extra="forbid")
    lines: dict[str, int]
    market: str = Field(min_length=1, max_length=120)      # the named target market
    verdict: str | None = Field(default=None, max_length=300)
    total: int | None = Field(default=None, ge=0, le=100)  # optional; checked against the lines

    @field_validator("lines")
    @classmethod
    def _lines(cls, v: dict[str, int]) -> dict[str, int]:
        return _rubric_lines(v)

    @field_validator("market", "verdict")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _one_line(v)

    @model_validator(mode="after")
    def _total(self) -> "Score":
        computed = sum(self.lines.values())
        if self.total is not None and self.total != computed:
            raise ValueError(f"total {self.total} is not the sum of the lines ({computed})")
        self.total = computed
        return self


class MoverNotes(BaseModel):
    """The founders' private take. Fields left out are kept as they are;
    a field sent as null is cleared."""
    model_config = ConfigDict(extra="forbid")
    take: str | None = Field(default=None, max_length=1500)       # how it helps us
    learn: str | None = Field(default=None, max_length=1000)      # what to learn
    localize: str | None = Field(default=None, max_length=1000)   # where to localize
    score: Score | None = None

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
    # omitted: a new mover is proposed (founders only until one of them
    # publishes it), an existing one keeps its status
    status: MoverStatus | None = None
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


class VoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voter: Founder
    vote: Literal[-1, 0, 1]                                  # 0 takes the vote back
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _one_line(v)


class StageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voter: Founder
    stage: MoverStage


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voter: Founder
    status: MoverStatus


def _required_line(v: str | None) -> str:
    out = _one_line(v)
    if not out:
        raise ValueError("must not be blank")
    return out


class Finding(BaseModel):
    """One thing a research run found. Consecutive findings with the same
    group share a heading ("How they grew")."""
    model_config = ConfigDict(extra="forbid")
    group: str | None = Field(default=None, max_length=60)
    title: str | None = Field(default=None, max_length=160)   # the lead, in bold
    text: str = Field(min_length=1, max_length=900)

    @field_validator("group", "title")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _one_line(v)

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        return _required_line(v)


class SourceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=120)
    url: str

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        return _required_line(v)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        url = svlib.canonical_url(v)
        if not url.startswith("https://"):
            raise ValueError("url must be an https URL")
        return url


class IdeaIn(BaseModel):
    """A localized idea, scored on the rubric for one named market. lines may
    be left out when only the total was recorded; when sent, they must add up."""
    model_config = ConfigDict(extra="forbid")
    idea: str = Field(min_length=1, max_length=200)      # "Reference -> our localized version"
    market: str = Field(min_length=1, max_length=120)
    total: int = Field(ge=0, le=100)
    lines: dict[str, int] | None = None
    note: str | None = Field(default=None, max_length=300)
    mover_id: Annotated[str, Field(pattern=MOVER_ID)] | None = None   # when it became a mover

    @field_validator("idea", "market")
    @classmethod
    def _required(cls, v: str) -> str:
        return _required_line(v)

    @field_validator("note")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _one_line(v)

    @field_validator("lines")
    @classmethod
    def _lines(cls, v: dict[str, int] | None) -> dict[str, int] | None:
        return None if v is None else _rubric_lines(v)

    @model_validator(mode="after")
    def _adds_up(self) -> "IdeaIn":
        if self.lines is not None and sum(self.lines.values()) != self.total:
            raise ValueError(f"total {self.total} is not the sum of the lines ({sum(self.lines.values())})")
        return self


class ResearchRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Annotated[str, Field(pattern=MOVER_ID)]          # "2026-10-22-example-lead"
    title: str = Field(min_length=1, max_length=160)
    run_date: date
    outcome: ResearchOutcome
    verdict: str = Field(min_length=1, max_length=120)   # "Out, 30"
    summary: str | None = Field(default=None, max_length=1500)
    method: str | None = Field(default=None, max_length=1500)
    findings: list[Finding] = Field(default_factory=list, max_length=20)
    sources: list[SourceLink] = Field(default_factory=list, max_length=15)
    refs: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=12)
    position: int = Field(default=0, ge=0, le=999)       # order among runs of the same day
    ideas: list[IdeaIn] = Field(default_factory=list, max_length=60)

    @field_validator("title", "verdict")
    @classmethod
    def _required(cls, v: str) -> str:
        return _required_line(v)

    @field_validator("summary", "method")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _one_line(v)

    @field_validator("refs")
    @classmethod
    def _refs(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(_required_line(x) for x in v))

    @field_validator("run_date")
    @classmethod
    def _run_date(cls, v: date) -> date:
        if v > svlib.today_pt() + timedelta(days=1):
            raise ValueError("run_date is in the future")
        return v

    @model_validator(mode="after")
    def _outcome(self) -> "ResearchRunIn":
        best = max((i.total for i in self.ideas), default=None)
        if self.outcome == "makes_list" and (best is None or best < RESEARCH_CUTOFF):
            raise ValueError(f"outcome makes_list needs an idea at {RESEARCH_CUTOFF} or more")
        if self.outcome == "below_cutoff" and (best is None or best >= RESEARCH_CUTOFF):
            raise ValueError(f"outcome below_cutoff needs scored ideas, all under {RESEARCH_CUTOFF}")
        return self


class ResearchIn(BaseModel):
    runs: list[dict[str, Any]] = Field(max_length=20)    # validated one by one, like movers


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
# news_count: every story pointing here; news_recent: those published in the
# trending window, which is what "Trending" sorts by.
MOVER_NEWS = f"""
    left join lateral (
        select count(*) news_count, max(coalesce(i.published_at, i.discovered_at)) latest_news_at,
               count(*) filter (where coalesce(i.published_at, i.discovered_at) > now() - interval '{TRENDING_WINDOW}') news_recent
        from mover_items mi join items i on i.id = mi.item_id where mi.mover_id = m.id
    ) n on true
"""
MOVER_ORDER = {
    "trending": "n.news_recent desc, n.latest_news_at desc nulls last, m.updated_at desc, m.name",
    "newest": "m.first_added_at desc, m.name",
}


def _mover_json(row: dict) -> dict:
    return {k: _iso(v) for k, v in row.items()}


@app.get("/v1/movers", dependencies=[Depends(require_read)])
def movers(
    kind: MoverKind | None = None,
    sort: Literal["trending", "newest"] = "trending",
    limit: Annotated[int, Query(ge=1, le=100)] = 60,
    offset: Annotated[int, Query(ge=0, le=5000)] = 0,
) -> dict:
    """Movers being watched, with how many stories feed each. Trending: most
    stories in the last 14 days first; newest: most recently added first."""
    where, args = ["m.status = 'watching'"], []
    if kind:
        where.append("m.kind = %s"); args.append(kind)
    cond = " and ".join(where)
    with pool.connection() as conn:
        total = conn.execute(f"select count(*) n from movers m where {cond}", args).fetchone()["n"]
        rows = conn.execute(
            f"select {MOVER_COLUMNS}, n.news_count, n.latest_news_at, n.news_recent from movers m {MOVER_NEWS} "
            f"where {cond} order by {MOVER_ORDER[sort]} limit %s offset %s", [*args, limit, offset]
        ).fetchall()
        kinds = conn.execute(
            "select coalesce(jsonb_object_agg(kind, n), '{}') k from (select kind, count(*) n from movers "
            "where status = 'watching' group by kind) t"
        ).fetchone()["k"]
    return {"total": total, "movers": [_mover_json(r) for r in rows], "facets": {"kinds": kinds}}


def _mover_items(conn, mover_id: str) -> list[dict]:
    items = conn.execute(
        f"select {ITEM_COLUMNS}, f.feed_date from mover_items mi join items i on i.id = mi.item_id "
        "left join feed_entries f on f.item_id = i.id where mi.mover_id = %s "
        "order by coalesce(i.published_at, i.discovered_at) desc limit 20", (mover_id,)
    ).fetchall()
    mentions = _mentions_for(conn, [r["id"] for r in items])
    return [_item_json(r, mentions[r["id"]]) for r in items]


@app.get("/v1/movers/updates", dependencies=[Depends(require_read)])
def mover_updates(limit: Annotated[int, Query(ge=1, le=200)] = 60) -> dict:
    """What changed on the list, newest first: movers added and new stories
    pointing at one. Public lines only, never who did it, and only for movers
    that are on the list now."""
    with pool.connection() as conn:
        rows = conn.execute(
            "select e.id, e.at, e.kind, e.mover_id, m.name, m.kind mover_kind, "
            "case when e.kind = 'news' then (e.detail->>'count')::int end count "
            "from mover_events e join movers m on m.id = e.mover_id "
            "where not e.private and e.kind in ('added', 'news') and m.status = 'watching' "
            "order by e.at desc, e.id desc limit %s", (limit,)
        ).fetchall()
    return {"updates": [_mover_json(r) for r in rows]}


@app.get("/v1/movers/{mover_id}", dependencies=[Depends(require_read)])
def mover(mover_id: Annotated[str, PathParam(pattern=MOVER_ID)]) -> dict:
    with pool.connection() as conn:
        row = conn.execute(
            f"select {MOVER_COLUMNS}, n.news_count, n.latest_news_at, n.news_recent from movers m {MOVER_NEWS} "
            "where m.id = %s and m.status = 'watching'", (mover_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "no such mover")
        items = _mover_items(conn, mover_id)
    return _mover_json(row) | {"items": items}


# ---------------------------------------------------------------- founders' desk
#
# Everything below answers only to the founders token, which only a
# founders-unlocked page on the Vercel server sends. Responses are never cached.

DESK_COLUMNS = f"""
    {MOVER_COLUMNS}, m.status, m.added_by, n.news_count, n.latest_news_at, n.news_recent,
    mn.take, mn.learn, mn.localize, mn.score, coalesce(mn.stage, 'new') stage, mn.updated_at notes_updated_at,
    coalesce(v.votes, '[]') votes, coalesce(v.net, 0) net_votes
"""
DESK_JOINS = f"""
    {MOVER_NEWS}
    left join mover_notes mn on mn.mover_id = m.id
    left join lateral (
        select jsonb_agg(jsonb_build_object('voter', mv.voter, 'vote', mv.vote, 'reason', mv.reason, 'at', mv.updated_at)
                         order by mv.updated_at desc) votes, sum(mv.vote) net
        from mover_votes mv where mv.mover_id = m.id
    ) v on true
"""
DESK_ORDER = {
    "fit": "(mn.score->>'total')::int desc nulls last, coalesce(v.net, 0) desc, m.name",
    "votes": "coalesce(v.net, 0) desc, (mn.score->>'total')::int desc nulls last, m.name",
    **MOVER_ORDER,
}


def _desk_json(row: dict) -> dict:
    out = _mover_json(row)
    out["notes"] = {k: out.pop(k) for k in ("take", "learn", "localize")}
    out["notes"]["updated_at"] = out.pop("notes_updated_at")
    return out


@app.get("/v1/private/desk", dependencies=[Depends(require_founders)])
def desk(
    response: Response,
    status: MoverStatus | Literal["active"] | None = None,
    kind: MoverKind | None = None,
    stage: MoverStage | None = None,
    sort: Literal["fit", "votes", "trending", "newest"] = "fit",
) -> dict:
    """Every mover with the founders' take, score, stage and votes. Proposed
    movers are here and nowhere public. status "active" means proposed or
    watching. Facets: status over everything; kind and stage within the
    status asked for (so a filter's count matches what it shows); and
    stage_active, stages over everything not archived."""
    response.headers["Cache-Control"] = "no-store"
    scope, scope_args = ("m.status <> 'archived'", []) if status == "active" else (("m.status = %s", [status]) if status else ("true", []))
    where, args = [scope], list(scope_args)
    for col, val in (("m.kind", kind), ("coalesce(mn.stage, 'new')", stage)):
        if val:
            where.append(f"{col} = %s"); args.append(val)
    stage_counts = ("select coalesce(jsonb_object_agg(stage, n), '{{}}') from (select coalesce(mn.stage, 'new') stage, count(*) n "
                    "from movers m left join mover_notes mn on mn.mover_id = m.id where {} group by 1) t")
    with pool.connection() as conn:
        rows = conn.execute(
            f"select {DESK_COLUMNS} from movers m {DESK_JOINS} where {' and '.join(where)} "
            f"order by {DESK_ORDER[sort]} limit 300", args
        ).fetchall()
        facets = conn.execute(
            "select jsonb_build_object("
            "'status', (select coalesce(jsonb_object_agg(status, n), '{}') from (select status, count(*) n from movers group by status) t), "
            f"'kind', (select coalesce(jsonb_object_agg(kind, n), '{{}}') from (select kind, count(*) n from movers m where {scope} group by kind) t), "
            f"'stage', ({stage_counts.format(scope)}), "
            f"'stage_active', ({stage_counts.format("m.status <> 'archived'")})) f",
            scope_args * 2,
        ).fetchone()["f"]
    return {"movers": [_desk_json(r) for r in rows], "facets": facets}


@app.get("/v1/private/movers/{mover_id}", dependencies=[Depends(require_founders)])
def desk_mover(response: Response, mover_id: Annotated[str, PathParam(pattern=MOVER_ID)]) -> dict:
    """One mover in any status, with everything the desk knows and its history."""
    response.headers["Cache-Control"] = "no-store"
    with pool.connection() as conn:
        row = conn.execute(f"select {DESK_COLUMNS} from movers m {DESK_JOINS} where m.id = %s", (mover_id,)).fetchone()
        if not row:
            raise HTTPException(404, "no such mover")
        items = _mover_items(conn, mover_id)
        events = conn.execute(
            "select id, at, kind, actor, detail from mover_events where mover_id = %s order by at desc, id desc limit 50",
            (mover_id,),
        ).fetchall()
    return _desk_json(row) | {"items": items, "events": [_mover_json(e) for e in events]}


@app.get("/v1/private/updates", dependencies=[Depends(require_founders)])
def desk_updates(response: Response, limit: Annotated[int, Query(ge=1, le=300)] = 100) -> dict:
    """The full log: proposals, votes, stages, scores and publishing, with who did it."""
    response.headers["Cache-Control"] = "no-store"
    with pool.connection() as conn:
        rows = conn.execute(
            "select e.id, e.at, e.kind, e.actor, e.detail, e.private, e.mover_id, m.name, m.kind mover_kind, m.status "
            "from mover_events e join movers m on m.id = e.mover_id order by e.at desc, e.id desc limit %s", (limit,)
        ).fetchall()
    return {"updates": [_mover_json(r) for r in rows]}


def _event(conn, mover_id: str, kind: str, actor: str, detail: dict | None = None) -> None:
    """Record what changed. Only 'added' and 'news' are public lines."""
    conn.execute(
        "insert into mover_events (mover_id, kind, actor, detail, private) values (%s, %s, %s, %s, %s)",
        (mover_id, kind, actor, Jsonb(detail or {}), kind not in ("added", "news")),
    )


STATUS_EVENT = {"proposed": "proposed", "watching": "added", "archived": "archived"}


def _desk_lock(conn, mover_id: str) -> dict:
    row = conn.execute("select status from movers where id = %s for update", (mover_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such mover")
    return row


@app.post("/v1/private/movers/{mover_id}/vote", dependencies=[Depends(require_founders)])
def desk_vote(mover_id: Annotated[str, PathParam(pattern=MOVER_ID)], body: VoteIn) -> dict:
    with pool.connection() as conn, conn.transaction():
        _desk_lock(conn, mover_id)
        if body.vote == 0:
            conn.execute("delete from mover_votes where mover_id = %s and voter = %s", (mover_id, body.voter))
        else:
            conn.execute(
                "insert into mover_votes (mover_id, voter, vote, reason) values (%s, %s, %s, %s) "
                "on conflict (mover_id, voter) do update set vote = excluded.vote, reason = excluded.reason, updated_at = now()",
                (mover_id, body.voter, body.vote, body.reason),
            )
        _event(conn, mover_id, "vote", body.voter, {"vote": body.vote, "reason": body.reason})
    return {"id": mover_id, "voter": body.voter, "vote": body.vote}


@app.post("/v1/private/movers/{mover_id}/stage", dependencies=[Depends(require_founders)])
def desk_stage(mover_id: Annotated[str, PathParam(pattern=MOVER_ID)], body: StageIn) -> dict:
    with pool.connection() as conn, conn.transaction():
        _desk_lock(conn, mover_id)
        old = conn.execute("select stage from mover_notes where mover_id = %s", (mover_id,)).fetchone()
        if (old["stage"] if old else "new") != body.stage:
            conn.execute(
                "insert into mover_notes (mover_id, stage, updated_by) values (%s, %s, %s) on conflict (mover_id) "
                "do update set stage = excluded.stage, updated_by = excluded.updated_by, updated_at = now()",
                (mover_id, body.stage, body.voter),
            )
            _event(conn, mover_id, "stage", body.voter, {"from": old["stage"] if old else "new", "to": body.stage})
    return {"id": mover_id, "stage": body.stage}


@app.post("/v1/private/movers/{mover_id}/status", dependencies=[Depends(require_founders)])
def desk_status(mover_id: Annotated[str, PathParam(pattern=MOVER_ID)], body: StatusIn) -> dict:
    """Publish a proposed mover (watching), take one off the list (archived),
    or send it back to the founders' queue (proposed)."""
    with pool.connection() as conn, conn.transaction():
        row = _desk_lock(conn, mover_id)
        if row["status"] != body.status:
            conn.execute("update movers set status = %s, updated_by = %s, updated_at = now() where id = %s",
                         (body.status, body.voter, mover_id))
            _event(conn, mover_id, STATUS_EVENT[body.status], body.voter, {"from": row["status"]})
    return {"id": mover_id, "status": body.status}


@app.get("/v1/private/research", dependencies=[Depends(require_founders)])
def research(response: Response) -> dict:
    """Every research run: verdict, how it was found, what it found, sources,
    and each idea it scored, including those under the cutoff. An idea that
    became a mover carries the mover's name and status."""
    response.headers["Cache-Control"] = "no-store"
    with pool.connection() as conn:
        runs = conn.execute(
            "select id, title, run_date, outcome, verdict, summary, method, findings, sources, refs, updated_by, updated_at "
            "from research_runs order by run_date desc, position, id"
        ).fetchall()
        ideas = conn.execute(
            "select ri.run_id, ri.position, ri.idea, ri.market, ri.total, ri.lines, ri.note, ri.mover_id, "
            "m.name mover_name, m.status mover_status "
            "from research_ideas ri left join movers m on m.id = ri.mover_id order by ri.run_id, ri.position"
        ).fetchall()
    by_run: dict[str, list[dict]] = {}
    for i in ideas:
        mover = {"id": i["mover_id"], "name": i["mover_name"], "status": i["mover_status"]} if i["mover_id"] else None
        by_run.setdefault(i["run_id"], []).append(
            {k: i[k] for k in ("position", "idea", "market", "total", "lines", "note")} | {"mover": mover})
    return {"cutoff": RESEARCH_CUTOFF, "runs": [_mover_json(r) | {"ideas": by_run.get(r["id"], [])} for r in runs]}


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
# A run may propose movers: a new one is "proposed" and only the founders see
# it, on their desk, until one of them publishes it there (or a founder's run
# sends status "watching" on purpose). Each write records the operator and a
# line in mover_events. Notes and scores go to mover_notes and nowhere else.

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


def _link(conn, mover_id: str, item_ids: list[str], operator: str) -> int:
    """Point these stories at a mover; returns how many were new links."""
    new = 0
    for iid in item_ids:
        new += conn.execute(
            "insert into mover_items (mover_id, item_id) values (%s, %s) on conflict do nothing", (mover_id, iid)
        ).rowcount
    if new:
        _event(conn, mover_id, "news", operator, {"count": new})
    return new


def _upsert_mover(conn, m: MoverIn, operator: str) -> bool:
    """Insert or replace a mover's public facts; True when it is new."""
    before = conn.execute("select status from movers where id = %s for update", (m.id,)).fetchone()
    row = conn.execute(
        """insert into movers (id, name, kind, url, one_liner, summary, traction, markets_live, claim_status, tags,
               image_url, image_kind, status, added_by, updated_by)
           values (%(id)s, %(name)s, %(kind)s, %(url)s, %(one_liner)s, %(summary)s, %(traction)s, %(markets)s,
               %(claim)s, %(tags)s, %(image_url)s, %(image_kind)s, coalesce(%(status)s, 'proposed'), %(op)s, %(op)s)
           on conflict (id) do update set
               name = excluded.name, kind = excluded.kind, url = excluded.url, one_liner = excluded.one_liner,
               summary = excluded.summary, traction = excluded.traction, markets_live = excluded.markets_live,
               claim_status = excluded.claim_status, tags = excluded.tags, image_url = excluded.image_url,
               image_kind = excluded.image_kind, status = coalesce(%(status)s, movers.status),
               updated_by = excluded.updated_by, updated_at = now()
           returning (xmax = 0) as inserted, status""",
        {
            "id": m.id, "name": m.name, "kind": m.kind, "url": m.url, "one_liner": m.one_liner, "summary": m.summary,
            "traction": Jsonb([t.model_dump(mode="json") for t in m.traction]), "markets": m.markets_live,
            "claim": m.claim_status, "tags": list(dict.fromkeys(m.tags)), "image_url": m.image_url,
            "image_kind": m.image_kind if m.image_url else None, "status": m.status, "op": operator,
        },
    ).fetchone()
    if before is None or before["status"] != row["status"]:
        _event(conn, m.id, STATUS_EVENT[row["status"]], operator)
    if m.notes is not None:
        _write_notes(conn, m.id, m.notes, operator)   # a subset of take / learn / localize / score (extra fields are refused)
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
                    linked = _link(conn, m.id, ids, operator)
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
    """Every mover (proposed, watching or archived), so a run can match stories to them."""
    with pool.connection() as conn:
        rows = conn.execute("select id, name, kind, url, status from movers order by name").fetchall()
    return {"movers": [dict(r) for r in rows]}


@app.post("/v1/ingest/movers/{mover_id}/link")
def link_mover(mover_id: Annotated[str, PathParam(pattern=MOVER_ID)], body: LinkIn,
               operator: Annotated[str, Depends(require_ingest)]) -> dict:
    with pool.connection() as conn:
        _mover_exists(conn, mover_id)
        ids, missing = _resolve_items(conn, body.item_urls)
        linked = _link(conn, mover_id, ids, operator)
    return {"id": mover_id, "linked": linked, "missing": missing}


@app.post("/v1/ingest/movers/{mover_id}/archive")
def archive_mover(mover_id: Annotated[str, PathParam(pattern=MOVER_ID)],
                  operator: Annotated[str, Depends(require_ingest)]) -> dict:
    with pool.connection() as conn, conn.transaction():
        row = _desk_lock(conn, mover_id)
        if row["status"] != "archived":
            conn.execute("update movers set status = 'archived', updated_by = %s, updated_at = now() where id = %s",
                         (operator, mover_id))
            _event(conn, mover_id, "archived", operator, {"from": row["status"]})
    return {"id": mover_id, "status": "archived"}


def _write_notes(conn, mover_id: str, notes: MoverNotes, operator: str) -> None:
    """Write the notes fields that were sent (null clears one) and log a new score."""
    fields = sorted(notes.model_fields_set)
    if not fields:
        return
    values = []
    for f in fields:
        v = getattr(notes, f)
        if f == "score" and v is not None:
            v = Jsonb(v.model_dump() | {"scored_at": svlib.today_pt().isoformat(), "scored_by": operator})
        values.append(v)
    conn.execute(
        f"insert into mover_notes (mover_id, {', '.join(fields)}, updated_by) values (%s, {', '.join(['%s'] * len(fields))}, %s) "
        f"on conflict (mover_id) do update set {', '.join(f'{f} = excluded.{f}' for f in fields)}, "
        "updated_by = excluded.updated_by, updated_at = now()",
        (mover_id, *values, operator),
    )
    if notes.score is not None:
        _event(conn, mover_id, "scored", operator, {"total": notes.score.total, "market": notes.score.market})


@app.post("/v1/ingest/movers/{mover_id}/notes")
def mover_notes(mover_id: Annotated[str, PathParam(pattern=MOVER_ID)], body: MoverNotes,
                operator: Annotated[str, Depends(require_ingest)]) -> dict:
    """Update only the founders' take or score (e.g. after an office-hours run),
    without resending the public facts."""
    if not body.model_fields_set:
        raise HTTPException(422, "send at least one of take, learn, localize, score")
    with pool.connection() as conn, conn.transaction():
        _desk_lock(conn, mover_id)
        _write_notes(conn, mover_id, body, operator)
    return {"id": mover_id, "updated": sorted(body.model_fields_set),
            "score": body.score.total if body.score is not None else None}


@app.get("/v1/ingest/movers/feedback")
def mover_feedback(operator: Annotated[str, Depends(require_ingest)]) -> dict:
    """What the founders thought of each mover: votes with reasons, stage,
    status and score. A run reads this before proposing more, so it learns
    what they want (more like the upvoted, none like the passed)."""
    with pool.connection() as conn:
        rows = conn.execute(
            f"select m.id, m.name, m.kind, m.tags, m.markets_live, m.status, coalesce(mn.stage, 'new') stage, "
            f"(mn.score->>'total')::int score, mn.score->>'market' score_market, "
            f"coalesce(v.votes, '[]') votes, coalesce(v.net, 0) net_votes from movers m {DESK_JOINS} "
            "order by m.updated_at desc"
        ).fetchall()
    return {"movers": [_mover_json(r) for r in rows]}


def _upsert_research(conn, r: ResearchRunIn, operator: str) -> tuple[bool, list[str]]:
    """Insert or replace a run and all of its ideas; returns (new, mover ids not found)."""
    row = conn.execute(
        """insert into research_runs (id, title, run_date, outcome, verdict, summary, method, findings, sources, refs,
               position, added_by, updated_by)
           values (%(id)s, %(title)s, %(run_date)s, %(outcome)s, %(verdict)s, %(summary)s, %(method)s, %(findings)s,
               %(sources)s, %(refs)s, %(position)s, %(op)s, %(op)s)
           on conflict (id) do update set
               title = excluded.title, run_date = excluded.run_date, outcome = excluded.outcome,
               verdict = excluded.verdict, summary = excluded.summary, method = excluded.method,
               findings = excluded.findings, sources = excluded.sources, refs = excluded.refs,
               position = excluded.position, updated_by = excluded.updated_by, updated_at = now()
           returning (xmax = 0) as inserted""",
        {
            "id": r.id, "title": r.title, "run_date": r.run_date, "outcome": r.outcome, "verdict": r.verdict,
            "summary": r.summary, "method": r.method, "position": r.position, "op": operator,
            "findings": Jsonb([f.model_dump() for f in r.findings]),
            "sources": Jsonb([s.model_dump() for s in r.sources]), "refs": Jsonb(r.refs),
        },
    ).fetchone()
    asked = sorted({i.mover_id for i in r.ideas if i.mover_id})
    known = {m["id"] for m in conn.execute("select id from movers where id = any(%s)", (asked,))} if asked else set()
    conn.execute("delete from research_ideas where run_id = %s", (r.id,))
    for pos, i in enumerate(r.ideas):
        conn.execute(
            "insert into research_ideas (run_id, position, idea, market, total, lines, note, mover_id) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s)",
            (r.id, pos, i.idea, i.market, i.total, Jsonb(i.lines) if i.lines is not None else None, i.note,
             i.mover_id if i.mover_id in known else None),
        )
    return bool(row["inserted"]), [m for m in asked if m not in known]


@app.post("/v1/ingest/research")
def ingest_research(body: ResearchIn, operator: Annotated[str, Depends(require_ingest)]) -> dict:
    """Record research runs for the founders' Research page. A run sent again
    replaces the stored one, ideas included. An idea's mover_id that is not a
    mover yet is reported and left unlinked."""
    results, counts = [], {"inserted": 0, "updated": 0, "rejected": 0}
    with pool.connection() as conn:
        for index, raw in enumerate(body.runs):
            try:
                r = ResearchRunIn.model_validate(raw)
            except Exception as exc:  # pydantic ValidationError or a URL ValueError
                counts["rejected"] += 1
                results.append({"index": index, "id": raw.get("id") if isinstance(raw.get("id"), str) else None,
                                "outcome": "rejected", "reason": str(exc)[:500]})
                continue
            try:
                with conn.transaction():
                    inserted, unlinked = _upsert_research(conn, r, operator)
            except Exception as exc:
                counts["rejected"] += 1
                results.append({"index": index, "id": r.id, "outcome": "rejected", "reason": f"database: {exc}"[:300]})
                continue
            outcome = "inserted" if inserted else "updated"
            counts[outcome] += 1
            results.append({"index": index, "id": r.id, "outcome": outcome, "ideas": len(r.ideas), "unlinked": unlinked})
    return {"operator": operator, **counts, "results": results}


@app.get("/v1/ingest/research")
def ingest_research_list(operator: Annotated[str, Depends(require_ingest)]) -> dict:
    """What is stored: each run's id, title, verdict, idea count and best score."""
    with pool.connection() as conn:
        rows = conn.execute(
            "select r.id, r.title, r.run_date, r.verdict, count(ri.id) ideas, max(ri.total) best "
            "from research_runs r left join research_ideas ri on ri.run_id = r.id "
            "group by r.id order by r.run_date desc, r.position, r.id"
        ).fetchall()
    return {"runs": [_mover_json(r) for r in rows]}
