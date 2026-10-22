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
os.environ["SV_DATABASE_URL"] = TEST_DB
os.environ["SV_READ_TOKEN_SHA256"] = hashlib.sha256(READ.encode()).hexdigest()

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
        conn.execute("drop table if exists feed_entries, mentions, runs, items, ingest_tokens, schema_migrations cascade")
        manage.migrate(conn)
        token = manage.issue_token(conn, "tester")
    with TestClient(api.app) as c:
        c.ingest = {"Authorization": f"Bearer {token}"}
        c.read = {"Authorization": f"Bearer {READ}"}
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
