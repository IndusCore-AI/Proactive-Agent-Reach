"""API tests against a real, throwaway Postgres database.

  SV_TEST_DATABASE_URL=postgresql://.../induscore_sv_test pytest sv/api/tests

Skipped when the variable or the API's dependencies are missing, so the
repository's own CI (which installs only agent-reach) is unaffected.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone

import pytest

TEST_DB = os.environ.get("SV_TEST_DATABASE_URL")
if not TEST_DB:
    pytest.skip("SV_TEST_DATABASE_URL not set", allow_module_level=True)
pytest.importorskip("fastapi")
psycopg = pytest.importorskip("psycopg")

READ = "test-read-token"
PRIVATE = "test-private-token"
os.environ["SV_DATABASE_URL"] = TEST_DB
os.environ["SV_READ_TOKEN_SHA256"] = hashlib.sha256(READ.encode()).hexdigest()
os.environ["SV_PRIVATE_READ_TOKEN_SHA256"] = hashlib.sha256(PRIVATE.encode()).hexdigest()

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

import app as api  # noqa: E402
import manage  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def client():
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("drop table if exists mover_items, mover_notes, movers, feed_entries, mentions, runs, items, ingest_tokens, "
                     "schema_migrations cascade")
        manage.migrate(conn)
        token = manage.issue_token(conn, "tester")
    with TestClient(api.app) as c:
        c.ingest = {"Authorization": f"Bearer {token}"}
        c.read = {"Authorization": f"Bearer {READ}"}
        c.private = {"Authorization": f"Bearer {PRIVATE}"}
        yield c


def item(**kw):
    base = {
        "url": "https://techcrunch.com/2026/10/21/acme-raises-12m-series-a/?utm_source=x",
        "title": "Acme raises $12M Series A to build robot kitchens",
        "source": "techcrunch", "source_name": "TechCrunch", "category": "funding",
        "tags": ["robotics", "funding"], "excerpt": "Acme said on Tuesday it raised $12M.",
        "published_at": (NOW - timedelta(hours=5)).isoformat(), "claim_status": "confirmed",
        "funding": {"company": "Acme", "round": "Series A", "amount": "$12M", "investors": ["Example Ventures"]},
        "score": 70,
    }
    base.update(kw)
    return base


def start(client, day=None):
    day = day or api.svlib.today_pt().isoformat()
    r = client.post("/v1/ingest/runs", json={"feed_date": day}, headers=client.ingest)
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


def test_auth_required(client):
    assert client.get("/v1/feed").status_code == 401
    assert client.get("/v1/feed", headers={"Authorization": "Bearer nope"}).status_code == 403
    assert client.post("/v1/ingest/runs", json={"feed_date": "2026-10-01"}, headers=client.read).status_code == 403
    assert client.get("/v1/health").json() == {"ok": True}


def test_rejects_future_and_malformed(client):
    tomorrow = (api.svlib.today_pt() + timedelta(days=1)).isoformat()
    assert client.post("/v1/ingest/runs", json={"feed_date": tomorrow}, headers=client.ingest).status_code == 422
    run = start(client)
    bad = [
        item(url="javascript:alert(1)"),
        item(url="http://localhost/x"),
        item(url="https://10.0.0.1/x"),
        item(title="<script>x</script> hi"),
        item(category="rumour"),
        item(published_at=(NOW + timedelta(days=2)).isoformat()),
        {"url": "https://example.com"},
    ]
    r = client.post(f"/v1/ingest/runs/{run}/items", json={"items": bad}, headers=client.ingest).json()
    assert r["rejected"] == len(bad) and r["inserted"] == 0
    client.post(f"/v1/ingest/runs/{run}/finish", json={"status": "failed"}, headers=client.ingest)


def test_ingest_is_idempotent_and_dedupes(client):
    run = start(client)
    hn = {"url": "https://news.ycombinator.com/item?id=4242", "source": "hackernews", "label": "Hacker News", "points": 310, "comments": 120}
    batch = [
        item(mentions=[hn]),
        # same URL with different tracking + www: same story
        item(url="https://www.techcrunch.com/2026/10/21/acme-raises-12m-series-a/?fbclid=1", source="hackernews", source_name="techcrunch.com", score=50),
        # syndicated headline under another URL: near-duplicate
        item(url="https://siliconangle.com/2026/10/21/acme-raises-12m-series-robot-kitchens/", source="siliconangle",
             source_name="SiliconANGLE", title="Acme raises $12M in Series A to build robot kitchens", score=40),
        item(url="https://www.ycombinator.com/launches/abc-widgets", title="Widgets for agents that never forget",
             source="yc-launches", source_name="YC Launches", category="launch", tags=["ai", "yc"], funding=None, score=55),
    ]
    r1 = client.post(f"/v1/ingest/runs/{run}/items", json={"items": batch}, headers=client.ingest).json()
    assert (r1["inserted"], r1["merged"], r1["rejected"]) == (2, 2, 0), r1
    fin = client.post(f"/v1/ingest/runs/{run}/finish", json={"status": "complete", "sources": [
        {"source": "techcrunch", "ok": True, "fetched": 20, "kept": 1},
        {"source": "reddit", "ok": False, "error": "HTTP 429"},
    ]}, headers=client.ingest).json()
    assert fin["status"] == "partial" and fin["edition_items"] == 2

    # rerun the same date: nothing new, nothing duplicated
    run2 = start(client)
    r2 = client.post(f"/v1/ingest/runs/{run2}/items", json={"items": batch}, headers=client.ingest).json()
    assert r2["inserted"] == 0 and r2["rejected"] == 0
    client.post(f"/v1/ingest/runs/{run2}/finish", json={"status": "complete"}, headers=client.ingest)

    feed = client.get("/v1/feed", headers=client.read).json()
    assert feed["total"] == 2
    top = feed["items"][0]
    assert top["title"].startswith("Acme raises") and top["rank"] == 1
    assert top["url"] == "https://techcrunch.com/2026/10/21/acme-raises-12m-series-a"
    labels = {m["label"] for m in top["mentions"]}
    assert {"Hacker News", "SiliconANGLE"} <= labels
    assert feed["run"]["status"] == "complete"


def test_item_stays_in_one_edition(client):
    yesterday = (api.svlib.today_pt() - timedelta(days=1)).isoformat()
    run = start(client, yesterday)
    r = client.post(f"/v1/ingest/runs/{run}/items", json={"items": [item()]}, headers=client.ingest).json()
    assert r["results"][0]["note"] == "already in another edition"
    client.post(f"/v1/ingest/runs/{run}/finish", json={"status": "complete"}, headers=client.ingest)
    assert client.get(f"/v1/feed?date={yesterday}", headers=client.read).json()["total"] == 0


def test_empty_date_and_detail_and_search(client):
    assert client.get("/v1/feed?date=2026-02-03", headers=client.read).json()["total"] == 0
    feed = client.get("/v1/feed", headers=client.read).json()
    one = client.get(f"/v1/items/{feed['items'][0]['id']}", headers=client.read).json()
    assert one["feed_date"] == feed["date"] and one["funding"]["company"] == "Acme"
    assert client.get("/v1/items/zzzzzzzzzzzz", headers=client.read).status_code == 404
    assert client.get("/v1/items/../../etc", headers=client.read).status_code in (404, 422)
    s = client.get("/v1/search?q=robot kitchens", headers=client.read).json()
    assert s["total"] >= 1
    assert client.get("/v1/topics/robotics", headers=client.read).json()["total"] == 1
    assert any(d["count"] == 2 for d in client.get("/v1/dates", headers=client.read).json()["dates"])


def test_filters_and_embed(client):
    run = start(client)
    x = item(url="https://twitter.com/founder/status/1850000000000000001?s=20", title="We just shipped v2 of our agent runtime",
             source="x", source_name="X", category="launch", tags=["ai"], funding=None, claim_status="unverified", score=30)
    r = client.post(f"/v1/ingest/runs/{run}/items", json={"items": [x]}, headers=client.ingest).json()
    assert r["inserted"] == 1, r
    client.post(f"/v1/ingest/runs/{run}/finish", json={"status": "complete"}, headers=client.ingest)
    launches = client.get("/v1/feed?category=launch&source=x", headers=client.read).json()
    assert launches["total"] == 1
    assert launches["items"][0]["embed"] == {"type": "x", "ref": "1850000000000000001"}
    assert launches["items"][0]["url"] == "https://x.com/founder/status/1850000000000000001"


def test_images_and_embeds(client):
    run = start(client)
    good = item(url="https://example.com/launch-one", title="Example launches a robot barista for offices",
                source="example", source_name="Example", category="launch", funding=None,
                image_url="https://cdn.example.com/og.png?w=1200&h=630", image_kind="cover",
                embed_url="https://x.com/founder/status/1850000000000000002", score=40)
    bad = [item(url=f"https://example.com/bad-{i}", title=f"Bad image story number {i} for testing", source="example",
                source_name="Example", category="news", funding=None, image_url=u, score=10)
           for i, u in enumerate(["http://cdn.example.com/a.png", "javascript:alert(1)", "https://localhost/a.png",
                                  'https://cdn.example.com/a.png" onerror="x'])]
    r = client.post(f"/v1/ingest/runs/{run}/items", json={"items": [good, *bad]}, headers=client.ingest).json()
    assert (r["inserted"], r["rejected"]) == (1, 4), r
    client.post(f"/v1/ingest/runs/{run}/finish", json={"status": "complete"}, headers=client.ingest)
    one = client.get(f"/v1/items/{r['results'][0]['id']}", headers=client.read).json()
    assert one["image_url"] == "https://cdn.example.com/og.png?w=1200&h=630" and one["image_kind"] == "cover"
    assert one["embed"] == {"type": "x", "ref": "1850000000000000002"}


def test_finish_twice_conflicts(client):
    run = start(client)
    assert client.post(f"/v1/ingest/runs/{run}/finish", json={"status": "complete"}, headers=client.ingest).status_code == 200
    assert client.post(f"/v1/ingest/runs/{run}/finish", json={"status": "complete"}, headers=client.ingest).status_code == 409
    assert client.post(f"/v1/ingest/runs/{run}/items", json={"items": [item()]}, headers=client.ingest).status_code == 409


# ---------------------------------------------------------------- movers

ACME_URL = "https://techcrunch.com/2026/10/21/acme-raises-12m-series-a"
NOTE_TEXT = ("TAKE-only-for-founders-7f3a", "LEARN-only-for-founders-9b1c", "LOCALIZE-only-for-founders-2d4e")
NOTE_KEYS = {"take", "learn", "localize"}


def mover(**kw):
    base = {
        "id": "example-robotics", "name": "Example Robotics", "kind": "company",
        "url": "https://www.example.com/?utm_source=x", "one_liner": "Robot arms for small kitchens.",
        "summary": "Example Robotics sells a countertop robot arm to independent restaurants.",
        "traction": [{"label": "Restaurants live", "value": "120", "source_url": "https://example.com/blog/120",
                      "as_of": "2026-10-01"}],
        "markets_live": ["US", "UK"], "claim_status": "confirmed", "tags": ["robotics"],
        "image_url": "https://cdn.example.com/logo.png", "image_kind": "logo",
    }
    base.update(kw)
    return base


def post_movers(client, movers):
    r = client.post("/v1/ingest/movers", json={"movers": movers}, headers=client.ingest)
    assert r.status_code == 200, r.text
    return r.json()


def keys_in(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_in(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_in(v)}
    return set()


def test_mover_traction_needs_a_source(client):
    line = {"label": "Users", "value": "10k", "as_of": "2026-10-01"}
    bad = [
        mover(traction=[line]),                                                     # no source at all
        mover(traction=[{**line, "source_url": ""}]),
        mover(traction=[{**line, "source_url": "http://example.com/plain-http"}]),
        mover(traction=[{**line, "source_url": "https://localhost/x"}]),
        mover(traction=[{**line, "source_url": "https://example.com/a", "as_of": "2999-01-01"}]),
        mover(traction=[{**line, "source_url": f"https://example.com/{i}"} for i in range(9)]),
        mover(id="unlock"), mover(id="Example_Robotics"), mover(id="x"),
        mover(kind="person"), mover(claim_status="opinion"), mover(one_liner="x" * 201),
        mover(take="top-level notes are refused, not dropped"),
        mover(notes={"takes": "typo"}),
        mover(name="<b>Example</b>"),
        mover(image_url="http://cdn.example.com/logo.png"),
    ]
    r = post_movers(client, bad)
    assert (r["inserted"], r["updated"], r["rejected"]) == (0, 0, len(bad)), r
    assert "source_url" in r["results"][0]["reason"]
    assert client.post("/v1/ingest/movers", json={"movers": [mover()]}, headers=client.read).status_code == 403
    assert client.post("/v1/ingest/movers", json={"movers": [mover()] * 51}, headers=client.ingest).status_code == 422


def test_mover_ingest_links_and_reports_missing(client):
    take, learn, localize = NOTE_TEXT
    r = post_movers(client, [
        mover(notes={"take": take, "learn": learn, "localize": localize},
              item_urls=[ACME_URL + "?utm_campaign=x", "https://www.ycombinator.com/launches/abc-widgets",
                         "https://example.com/never-ingested", "javascript:alert(1)"]),
        mover(id="example-notes-app", name="Example Notes App", kind="app", one_liner="A notes app for field teams.",
              traction=[], markets_live=["India"], claim_status="unverified", image_url=None, image_kind=None),
    ])
    assert (r["inserted"], r["rejected"]) == (2, 0), r
    first = r["results"][0]
    assert first["outcome"] == "inserted" and first["linked"] == 2 and first["notes"] is True
    assert first["missing"] == ["https://example.com/never-ingested", "javascript:alert(1)"]

    # A story merged into another is found through its recorded sighting.
    linked = client.post("/v1/ingest/movers/example-robotics/link", headers=client.ingest, json={"item_urls": [
        "https://siliconangle.com/2026/10/21/acme-raises-12m-series-robot-kitchens/",
        "https://x.com/founder/status/1850000000000000001", "https://example.com/nope"]}).json()
    assert linked == {"id": "example-robotics", "linked": 2, "missing": ["https://example.com/nope"]}
    assert client.post("/v1/ingest/movers/no-such-mover/link", json={"item_urls": [ACME_URL]},
                       headers=client.ingest).status_code == 404

    one = client.get("/v1/movers/example-robotics", headers=client.read).json()
    assert one["news_count"] == 3 and len(one["items"]) == 3
    assert one["url"] == "https://www.example.com/" and one["traction"][0]["source_url"] == "https://example.com/blog/120"
    stamps = [i["published_at"] or i["discovered_at"] for i in one["items"]]
    assert stamps == sorted(stamps, reverse=True)
    acme = next(i for i in one["items"] if i["url"] == ACME_URL)
    assert acme["feed_date"] and isinstance(acme["mentions"], list)

    item = client.get(f"/v1/items/{acme['id']}", headers=client.read).json()
    assert item["movers"] == [{"id": "example-robotics", "name": "Example Robotics", "kind": "company"}]

    # Rerun: updates in place; a notes field left out is kept.
    r2 = post_movers(client, [mover(one_liner="Robot arms for small restaurant kitchens.", notes={"take": take + " v2"})])
    assert r2["results"][0]["outcome"] == "updated" and r2["results"][0]["linked"] == 0
    notes = client.get("/v1/private/movers?ids=example-robotics", headers=client.private).json()
    assert notes["example-robotics"]["take"] == take + " v2" and notes["example-robotics"]["learn"] == learn

    listed = client.get("/v1/movers", headers=client.read).json()
    assert listed["total"] == 2 and listed["facets"]["kinds"] == {"company": 1, "app": 1}
    robo = next(m for m in listed["movers"] if m["id"] == "example-robotics")
    assert robo["news_count"] == 3 and robo["latest_news_at"]
    apps = client.get("/v1/movers?kind=app", headers=client.read).json()
    assert [m["id"] for m in apps["movers"]] == ["example-notes-app"] and apps["movers"][0]["news_count"] == 0
    assert client.get("/v1/movers?kind=person", headers=client.read).status_code == 422
    ids = client.get("/v1/ingest/movers", headers=client.ingest).json()["movers"]
    assert {(m["id"], m["kind"]) for m in ids} == {("example-robotics", "company"), ("example-notes-app", "app")}


def test_private_route_rejects_everything_but_its_own_token(client, monkeypatch):
    assert client.get("/v1/private/movers").status_code == 401
    assert client.get("/v1/private/movers", headers=client.read).status_code == 403
    assert client.get("/v1/private/movers", headers=client.ingest).status_code == 403
    assert client.get("/v1/private/movers", headers={"Authorization": "Bearer nope"}).status_code == 403
    # The private token opens nothing else.
    assert client.get("/v1/movers", headers=client.private).status_code == 403

    ok = client.get("/v1/private/movers", headers=client.private)
    assert ok.status_code == 200 and ok.headers["cache-control"] == "no-store"
    assert set(ok.json()) == {"example-robotics"}            # the app has no notes
    assert set(ok.json()["example-robotics"]) == {"take", "learn", "localize", "updated_at"}
    assert client.get("/v1/private/movers?ids=example-notes-app", headers=client.private).json() == {}
    assert client.get("/v1/private/movers?ids=Bad_Id", headers=client.private).status_code == 422

    monkeypatch.setattr(api, "PRIVATE_TOKEN_SHA256", "")                     # not configured
    assert client.get("/v1/private/movers", headers=client.private).status_code == 403
    monkeypatch.setattr(api, "PRIVATE_TOKEN_SHA256", api.READ_TOKEN_SHA256)   # misconfigured as the read token
    assert client.get("/v1/private/movers", headers=client.read).status_code == 403


PUBLIC_GETS = {
    "/v1/health": ["/v1/health"],
    "/v1/feed": ["/v1/feed", "/v1/feed?category=funding"],
    "/v1/dates": ["/v1/dates"],
    "/v1/items/{item_id}": [f"/v1/items/{api.svlib.item_id(ACME_URL)}"],
    "/v1/topics": ["/v1/topics"],
    "/v1/topics/{tag}": ["/v1/topics/robotics"],
    "/v1/search": ["/v1/search?q=robot"],
    "/v1/sitemap": ["/v1/sitemap"],
    "/v1/movers": ["/v1/movers", "/v1/movers?kind=company", "/v1/movers?kind=app"],
    "/v1/movers/{mover_id}": ["/v1/movers/example-robotics", "/v1/movers/example-notes-app"],
}


def test_no_public_route_returns_the_founders_take(client):
    # Every GET route outside /v1/private and /v1/ingest must be listed above,
    # so a new public route cannot skip this check.
    public = {r.path for r in api.app.routes if "GET" in getattr(r, "methods", set())
              and not r.path.startswith(("/v1/private/", "/v1/ingest/"))}
    assert public == set(PUBLIC_GETS), public ^ set(PUBLIC_GETS)
    for urls in PUBLIC_GETS.values():
        for url in urls:
            r = client.get(url, headers=client.read)
            assert r.status_code == 200, (url, r.text)
            assert not keys_in(r.json()) & NOTE_KEYS, url
            assert not any(t in r.text for t in NOTE_TEXT), url
    # ...and the ingest listing, which a run reads, carries no notes either.
    r = client.get("/v1/ingest/movers", headers=client.ingest)
    assert not keys_in(r.json()) & NOTE_KEYS and not any(t in r.text for t in NOTE_TEXT)


def test_archive_hides_mover_from_public_lists(client):
    client.post("/v1/ingest/movers/example-notes-app/link", json={"item_urls": [ACME_URL]}, headers=client.ingest)
    acme = api.svlib.item_id(ACME_URL)
    assert len(client.get(f"/v1/items/{acme}", headers=client.read).json()["movers"]) == 2

    r = client.post("/v1/ingest/movers/example-notes-app/archive", json={}, headers=client.ingest)
    assert r.json() == {"id": "example-notes-app", "status": "archived"}
    listed = client.get("/v1/movers", headers=client.read).json()
    assert [m["id"] for m in listed["movers"]] == ["example-robotics"] and listed["facets"]["kinds"] == {"company": 1}
    assert client.get("/v1/movers?kind=app", headers=client.read).json()["total"] == 0
    assert client.get("/v1/movers/example-notes-app", headers=client.read).status_code == 404
    assert [m["id"] for m in client.get("/v1/sitemap", headers=client.read).json()["movers"]] == ["example-robotics"]
    assert [m["id"] for m in client.get(f"/v1/items/{acme}", headers=client.read).json()["movers"]] == ["example-robotics"]
    assert client.post("/v1/ingest/movers/no-such-mover/archive", json={}, headers=client.ingest).status_code == 404

    # A rerun of the founder's file keeps it archived unless it says otherwise.
    app = mover(id="example-notes-app", name="Example Notes App", kind="app", one_liner="A notes app for field teams.",
                traction=[], image_url=None, image_kind=None)
    post_movers(client, [app])
    assert client.get("/v1/movers/example-notes-app", headers=client.read).status_code == 404
    post_movers(client, [{**app, "status": "watching"}])
    assert client.get("/v1/movers/example-notes-app", headers=client.read).status_code == 200
