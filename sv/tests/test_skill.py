"""Tests for the aggregation skill's pure logic: URL canonicalization, IDs,
duplicate detection, embed detection, feed parsing, scoring and merging.
Standard library only; no network."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "aggregate-silicon-valley" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import collect  # noqa: E402
import pytest  # noqa: E402
import svlib  # noqa: E402


@pytest.mark.parametrize("raw,expected", [
    ("https://techcrunch.com/2026/10/21/x/?utm_source=tw&utm_medium=social", "https://techcrunch.com/2026/10/21/x"),
    ("HTTPS://TechCrunch.com/a/#comments", "https://techcrunch.com/a"),
    ("https://twitter.com/sama/status/1850000000000000001?s=20&t=abc", "https://x.com/sama/status/1850000000000000001"),
    ("https://youtu.be/dQw4w9WgXcQ?si=xyz", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1&t=30", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("https://news.ycombinator.com/item?id=4242", "https://news.ycombinator.com/item?id=4242"),
    ("https://old.reddit.com/r/startups/comments/abc/x/", "https://www.reddit.com/r/startups/comments/abc/x"),
    ("https://example.com/search?q=ai&page=2&fbclid=1", "https://example.com/search?page=2&q=ai"),
])
def test_canonical_url(raw, expected):
    assert svlib.canonical_url(raw) == expected


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "ftp://x.com/a", "http://localhost/a", "https://10.1.2.3/",
                                 "https://user:pw@example.com/", "https://intranet.local/x", "", "https://exa mple.com"])
def test_canonical_url_rejects(bad):
    with pytest.raises(ValueError):
        svlib.canonical_url(bad)


def test_item_id_ignores_www_scheme_and_tracking():
    a = svlib.item_id("https://www.example.com/post/?utm_campaign=x")
    b = svlib.item_id("http://example.com/post")
    assert a == b and len(a) == 12 and a.isalnum()


def test_similar_titles():
    assert svlib.similar_titles("Acme raises $12M Series A to build robot kitchens",
                                "Acme raises $12M in Series A to build robot kitchens")
    assert not svlib.similar_titles("Acme raises $12M Series A", "Beta raises $40M Series B")
    assert not svlib.similar_titles("Show HN: Foo", "Show HN: Bar")


def test_detect_embed():
    assert svlib.detect_embed("https://x.com/paulg/status/1850000000000000001") == ("x", "1850000000000000001")
    assert svlib.detect_embed("https://youtu.be/dQw4w9WgXcQ") == ("youtube", "dQw4w9WgXcQ")
    assert svlib.detect_embed("https://www.youtube.com/shorts/dQw4w9WgXcQ") == ("youtube", "dQw4w9WgXcQ")
    assert svlib.detect_embed("https://x.com/paulg") is None
    assert svlib.detect_embed("https://techcrunch.com/a") is None


def test_edition_window_is_48h_ending_at_end_of_day_and_not_in_future():
    start, end = svlib.edition_window(date(2026, 10, 20), now=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert end - start == timedelta(hours=48)
    assert end.astimezone(svlib.PRODUCT_TZ).date() == date(2026, 10, 21)
    now = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
    assert svlib.edition_window(date(2026, 10, 22), now=now)[1] == now


RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item><title>Acme raises $12M Series A</title><link>https://techcrunch.com/acme/?utm_source=rss</link>
<pubDate>Wed, 21 Oct 2026 17:00:00 +0000</pubDate><dc:creator>Jane Doe</dc:creator>
<description><![CDATA[<p>Acme, which builds robot kitchens, raised $12 million led by Example Ventures.</p><p>The post Acme raises appeared first on TechCrunch.</p>]]></description></item>
<item><title>Old story</title><link>https://techcrunch.com/old</link><pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Sponkly</title><link rel="alternate" href="https://www.producthunt.com/products/sponkly"/>
<published>2026-10-21T16:31:26-07:00</published><content type="html">&lt;p&gt;Live voice translation for chats and calls.&lt;/p&gt;</content></entry>
</feed>"""


def test_parse_feeds():
    rss = collect.parse_feed(RSS)
    assert rss[0]["title"] == "Acme raises $12M Series A" and rss[0]["author"] == "Jane Doe"
    assert rss[0]["published"] == datetime(2026, 10, 21, 17, tzinfo=timezone.utc)
    atom = collect.parse_feed(ATOM)
    assert atom[0]["link"] == "https://www.producthunt.com/products/sponkly"
    assert atom[0]["published"] == datetime(2026, 10, 21, 23, 31, 26, tzinfo=timezone.utc)
    with pytest.raises(collect.SourceError):
        collect.parse_feed(b"<html>not a feed")


def test_rss_collector_window_excerpt_and_hints(monkeypatch):
    monkeypatch.setattr(collect, "fetch", lambda url, **kw: RSS)
    src = {"id": "techcrunch", "name": "TechCrunch", "kind": "rss", "url": "x", "weight": 17, "category": "news", "claim": "reported"}
    start = datetime(2026, 10, 21, tzinfo=timezone.utc)
    cands, fetched = collect.collect_rss(src, start, start + timedelta(days=1))
    assert fetched == 2 and len(cands) == 1
    c = cands[0]
    assert c["url"] == "https://techcrunch.com/acme"
    assert c["category"] == "funding" and c["funding_hint"] == {"amount": "$12M", "round": "Series A"}
    assert "appeared first" not in c["excerpt"] and c["excerpt"].startswith("Acme, which builds")


def test_merge_keeps_publisher_and_adds_hn_mention():
    src_tc = {"id": "techcrunch", "name": "TechCrunch", "weight": 17, "category": "news", "claim": "reported"}
    src_hn = {"id": "hackernews", "name": "Hacker News", "weight": 16, "category": "discussion", "claim": "reported"}
    now = datetime(2026, 10, 21, 18, tzinfo=timezone.utc)
    tc = collect.candidate(src_tc, url="https://techcrunch.com/acme", title="Acme raises $12M Series A to build robot kitchens", published=now)
    hn = collect.candidate(src_hn, url="https://www.techcrunch.com/acme/?ref=hn", title="Acme raises $12M Series A to build robot kitchens",
                           published=now, source_name="techcrunch.com", engagement={"points": 300, "comments": 120},
                           mentions=[{"url": "https://news.ycombinator.com/item?id=1", "source": "hackernews", "label": "Hacker News", "points": 300, "comments": 120}])
    merged = collect.merge([hn, tc])
    assert len(merged) == 1
    m = merged[0]
    assert m["source"] == "techcrunch" and set(m["found_in"]) == {"techcrunch", "hackernews"}
    assert any(x["label"] == "Hacker News" and x["points"] == 300 for x in m["mentions"])
    scored = collect.prescore(m, now + timedelta(hours=2))
    assert 0 <= scored["score"] <= 100 and scored["score_detail"]["multi_source"] == 5


def test_off_topic_is_penalised():
    src = {"id": "hackernews", "name": "Hacker News", "weight": 16, "category": "discussion", "claim": "reported"}
    now = datetime(2026, 10, 21, 18, tzinfo=timezone.utc)
    off = collect.prescore(collect.candidate(src, url="https://example.com/dice", title="Roman dice found in a field near the river", published=now), now)
    on = collect.prescore(collect.candidate(src, url="https://example.com/raise", title="Startup raises seed round for AI agents", published=now), now)
    assert off["score_detail"]["off_topic"] == -25 and on["score"] > off["score"]
