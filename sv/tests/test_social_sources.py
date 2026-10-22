"""Tests for the social and chart sources: YouTube channel feeds, the polite
Reddit fetcher, App Store chart movers, essay feeds and the optional
login-gated step. Fixtures live in sv/tests/fixtures/. No network."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "aggregate-silicon-valley" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SKILL_SOURCES = SCRIPTS.parent / "sources.json"
sys.path.insert(0, str(SCRIPTS))

import collect  # noqa: E402
import svlib  # noqa: E402


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def configured(kind: str) -> list[dict]:
    return [s for s in json.loads(SKILL_SOURCES.read_text())["sources"] if s["kind"] == kind]


# ---------------------------------------------------------------- YouTube

YT_SRC = {"id": "yt-example", "name": "Example Founders", "kind": "youtube", "channel_id": "UCexampleexampleexample0",
          "weight": 10, "filter": False, "category": "analysis", "claim": "opinion"}
WINDOW = (datetime(2026, 10, 20, 7, tzinfo=timezone.utc), datetime(2026, 10, 22, 7, tzinfo=timezone.utc))


def test_youtube_feed_parser():
    entries = collect.parse_youtube_feed(fixture("youtube_channel.xml"))
    assert [e["video_id"] for e in entries] == ["AbCdEfGhIj0", "ShOrTcLiP01", "OldVideo001"]   # a bad id is skipped
    first, short = entries[0], entries[1]
    assert first["url"] == "https://www.youtube.com/watch?v=AbCdEfGhIj0"
    assert first["published"] == datetime(2026, 10, 21, 15, 0, 16, tzinfo=timezone.utc)
    assert first["views"] == 48210 and first["likes"] == 1200 and first["short"] is False
    assert first["thumbnail"] == "https://i1.ytimg.com/vi/AbCdEfGhIj0/hqdefault.jpg"
    assert first["description"].startswith("The founder of an AI note-taking startup")
    assert short["short"] is True and short["url"] == "https://www.youtube.com/watch?v=ShOrTcLiP01"
    assert short["thumbnail"] == "https://i2.ytimg.com/vi/ShOrTcLiP01/hqdefault.jpg"            # upgraded to https
    assert entries[2]["views"] is None and entries[2]["thumbnail"] is None
    with pytest.raises(collect.SourceError):
        collect.parse_youtube_feed(b"<rss><channel></channel></rss>")
    with pytest.raises(collect.SourceError):
        collect.parse_youtube_feed(b"<html>")


def test_youtube_collector_keeps_window_drops_shorts_and_embeds(monkeypatch):
    seen = []
    monkeypatch.setattr(collect, "fetch", lambda url, **kw: seen.append(url) or fixture("youtube_channel.xml"))
    cands, fetched = collect.collect_youtube(YT_SRC, *WINDOW)
    assert seen == ["https://www.youtube.com/feeds/videos.xml?channel_id=UCexampleexampleexample0"]
    assert fetched == 3 and [c["url"] for c in cands] == ["https://www.youtube.com/watch?v=AbCdEfGhIj0"]
    c = cands[0]
    assert c["source"] == "yt-example" and c["source_name"] == "Example Founders" and c["author"] == "Example Founders"
    assert c["engagement"] == {"views": 48210, "likes": 1200} and c["image_url"].startswith("https://i1.ytimg.com/")
    assert c["claim_status"] == "opinion" and c["category"] == "analysis" and c["relevant"]
    # the site embeds the video from the story URL itself (the existing YouTube embed)
    assert svlib.detect_embed(c["url"]) == ("youtube", "AbCdEfGhIj0")
    # a channel that keeps Shorts gets them too, as watch URLs
    cands, _ = collect.collect_youtube({**YT_SRC, "shorts": True}, *WINDOW)
    assert {c["extra"]["video_id"] for c in cands} == {"AbCdEfGhIj0", "ShOrTcLiP01"}


def test_video_views_drive_engagement():
    now = datetime(2026, 10, 21, 18, tzinfo=timezone.utc)
    low = collect.prescore(collect.candidate(YT_SRC, url="https://www.youtube.com/watch?v=AAAAAAAAAAA", title="An AI startup interview",
                                             published=now, engagement={"views": 300}), now)
    high = collect.prescore(collect.candidate(YT_SRC, url="https://www.youtube.com/watch?v=BBBBBBBBBBB", title="An AI startup interview two",
                                              published=now, engagement={"views": 400_000}), now)
    assert high["score_detail"]["engagement"] == 35.0 and low["score"] < high["score"]


def test_chinese_titles_count_as_relevant():
    src = {**YT_SRC, "id": "yt-guigu101"}
    now = datetime(2026, 10, 21, 18, tzinfo=timezone.utc)
    zh = collect.candidate(src, url="https://www.youtube.com/watch?v=CCCCCCCCCCC", title="智能体手机加速爆发？端侧AI与下一代入口之争", published=now)
    assert zh["relevant"]
    # "AI" inside an English word is not a match
    assert not collect.RELEVANT_ZH.search("She said the train was late")


def test_configured_youtube_channels_are_well_formed():
    channels = configured("youtube")
    assert len(channels) >= 9
    for s in channels:
        assert s["channel_id"].startswith("UC") and len(s["channel_id"]) == 24, s["id"]
        assert len(s["id"]) <= 32 and len(s["name"]) <= 60
    assert len({s["channel_id"] for s in channels}) == len(channels)


# ---------------------------------------------------------------- Reddit


class FakeReddit:
    """Scripted answers for RedditFetcher, a fake clock and a record of waits."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls: list[str] = []
        self.now = 1000.0
        self.waits: list[float] = []

    def open(self, url):
        self.calls.append(url)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def sleep(self, s):
        self.waits.append(round(s, 1))
        self.now += s

    def clock(self):
        return self.now

    def fetcher(self):
        return collect.RedditFetcher(opener=self.open, sleep=self.sleep, clock=self.clock)


def test_reddit_waits_as_long_as_its_headers_ask():
    fake = FakeReddit([(200, {"x-ratelimit-remaining": "0.0", "x-ratelimit-reset": "30"}, b"one"),
                       (200, {"X-Ratelimit-Remaining": "5", "X-Ratelimit-Reset": "50"}, b"two"),
                       (200, {}, b"three")])
    r = fake.fetcher()
    assert r.get("https://www.reddit.com/a") == b"one"
    assert r.get("https://www.reddit.com/b") == b"two"
    assert r.get("https://www.reddit.com/c") == b"three"
    assert fake.waits == [31.0, 2.0]   # the reset plus a second, then the minimum gap


def test_reddit_retries_a_429_once_after_retry_after():
    fake = FakeReddit([(429, {"Retry-After": "12", "x-ratelimit-remaining": "0", "x-ratelimit-reset": "40"}, b""),
                       (200, {}, b"ok")])
    assert fake.fetcher().get("https://www.reddit.com/a") == b"ok"
    assert fake.waits == [12.0] and len(fake.calls) == 2


def test_reddit_gives_up_after_two_429s_and_skips_the_rest_of_the_run():
    fake = FakeReddit([(429, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "500"}, b""),
                       (429, {}, b"")])
    r = fake.fetcher()
    with pytest.raises(collect.SourceError, match="HTTP 429 from Reddit: rate-limited, waited and retried once"):
        r.get("https://www.reddit.com/a")
    assert fake.waits == [70.0]          # a long reset is capped, never an endless wait
    with pytest.raises(collect.SourceError, match="^not tried: Reddit rate-limited this run"):
        r.get("https://www.reddit.com/b")
    assert len(fake.calls) == 2          # the second source never reached Reddit


def test_reddit_refusals_are_not_retried_or_worked_around():
    fake = FakeReddit([(403, {}, b""), (404, {}, b""), (200, {}, b"fine")])
    r = fake.fetcher()
    with pytest.raises(collect.SourceError, match="HTTP 403 from Reddit \\(refused; not worked around\\)"):
        r.get("https://www.reddit.com/a")
    with pytest.raises(collect.SourceError, match="HTTP 404"):
        r.get("https://www.reddit.com/b")
    assert r.get("https://www.reddit.com/c") == b"fine" and r.blocked is None
    assert len(fake.calls) == 3


def test_reddit_network_error_is_retried_once():
    fake = FakeReddit([TimeoutError("slow"), TimeoutError("slow")])
    with pytest.raises(collect.SourceError, match="TimeoutError"):
        fake.fetcher().get("https://www.reddit.com/a")
    assert len(fake.calls) == 2


def test_reddit_collector_builds_one_feed_per_group(monkeypatch):
    fake = FakeReddit([(200, {}, fixture("reddit_top.xml"))])
    monkeypatch.setattr(collect, "REDDIT", fake.fetcher())
    src = {"id": "reddit-builders", "name": "Reddit (SaaS, side projects)", "kind": "reddit", "subreddits": ["SaaS", "SideProject"],
           "limit": 50, "weight": 7, "filter": False, "category": "discussion", "claim": "unverified"}
    cands, fetched = collect.collect_reddit(src, *WINDOW)
    assert fake.calls == ["https://www.reddit.com/r/SaaS+SideProject/top/.rss?t=day&limit=50"]
    assert fetched == 3 and [c["source_name"] for c in cands] == ["r/SaaS", "r/SideProject"]
    assert cands[1]["url"] == "https://www.reddit.com/r/SideProject/comments/1bbbbbb/i_built_a_free_library"
    assert cands[0]["claim_status"] == "unverified" and cands[0]["category"] == "discussion"
    assert cands[0]["extra"] == {"subreddit": "SaaS"} and cands[0]["engagement"] == {"top_rank": 1, "of": 3}
    first, second = (collect.prescore(c, WINDOW[1]) for c in cands)
    assert first["score_detail"]["engagement"] == 24.0 and second["score_detail"]["engagement"] == 16.0
    assert "submitted by" not in cands[0]["excerpt"]


def test_reddit_sources_share_one_lane_and_keep_their_order(monkeypatch):
    order = []

    def fake_run(src, start, end, is_today):
        order.append(src["id"])
        return {"source": src["id"], "ok": True}, []

    monkeypatch.setattr(collect, "run_source", fake_run)
    sources = [{"id": "techcrunch", "kind": "rss"}, {"id": "reddit", "kind": "reddit"}, {"id": "hn", "kind": "hn"},
               {"id": "reddit-ai", "kind": "reddit"}]
    results = collect.run_all(sources, *WINDOW, False)
    assert [r[0]["source"] for r in results] == ["techcrunch", "reddit", "hn", "reddit-ai"]
    assert order.index("reddit") < order.index("reddit-ai")


def test_configured_reddit_groups():
    groups = configured("reddit")
    subs = [s for g in groups for s in g["subreddits"]]
    for wanted in ("SaaS", "startups", "SideProject", "indiehackers", "ClaudeAI", "LocalLLaMA", "Entrepreneur", "StartUpIndia"):
        assert wanted in subs
    assert len(subs) == len(set(subs)) and len(groups) <= 4   # few requests: one per group
    assert all(g["claim"] == "unverified" for g in groups)


# ---------------------------------------------------------------- App Store chart movers

import charts  # noqa: E402


def test_apple_chart_parser():
    chart = charts.parse_chart(fixture("apple_chart_us_top_free.json"))
    assert chart["country"] == "us" and chart["updated"].startswith("Thu, 22 Oct 2026")
    assert [(a["id"], a["rank"]) for a in chart["apps"]] == [("407558537", 1), ("632064380", 2), ("6448311069", 4)]
    assert chart["apps"][2] == {"id": "6448311069", "name": "Example AI Chat", "artist": "Example AI Inc.",
                                "url": "https://apps.apple.com/us/app/example-ai-chat/id6448311069", "released": "2026-09-30", "rank": 4}
    for bad in (b"<html>", b'{"feed": {}}', b'{"feed": {"results": []}}'):
        with pytest.raises(ValueError):
            charts.parse_chart(bad)


def chart(country: str, chart_: str, ranked: list[str]) -> dict:
    """A loaded feed: app ids in rank order (None leaves a gap)."""
    return {"url": charts.FEED.format(country=country, chart=chart_),
            "apps": [{"id": i, "name": f"App {i}", "artist": f"Maker {i}", "url": f"https://apps.apple.com/{country}/app/id{i}",
                      "released": None, "rank": r} for r, i in enumerate(ranked, 1) if i]}


def snap(day: str, feeds: dict[str, list[str]], failed: tuple[str, ...] = ()) -> dict:
    out = {k: chart(*k.split("/"), v) for k, v in feeds.items()}
    out.update({k: {"url": charts.FEED.format(country=k.split("/")[0], chart=k.split("/")[1]), "error": "HTTP 503"} for k in failed})
    return {"date": day, "feeds": out}


def filler(n: int, prefix: str) -> list[str]:
    return [f"{prefix}{i}" for i in range(n)]


CFG = {"countries": ["us", "in", "gb", "de", "id", "sg", "my"], "charts": ["top-free"]}


def test_rising_new_and_up_25_places():
    before = snap("2026-10-21", {"us/top-free": ["a", "b"] + filler(40, "x") + ["late"] + filler(57, "y")})
    # "late" was 43rd and is now 10th (up 33); "b" slipped; "fresh" is new; "a" moved only 1 place
    after = snap("2026-10-22", {"us/top-free": ["b", "a"] + filler(7, "x") + ["late", "fresh"] + filler(30, "x")[9:]})
    doc = charts.compute_movers(after, before, CFG)
    moves = {e["app_id"]: e["moves"][0] for e in doc["rising"]}
    assert set(moves) == {"late", "fresh"}
    assert moves["late"] == {"country": "us", "rank": 10, "previous_rank": 43, "places_up": 33, "date": "2026-10-22",
                             "previous_date": "2026-10-21", "source": charts.FEED.format(country="us", chart="top-free")}
    assert moves["fresh"]["previous_rank"] is None and moves["fresh"]["places_up"] is None
    assert doc["previous_date"] == "2026-10-21"


def test_rising_groups_countries_and_skips_feeds_missing_before():
    before = snap("2026-10-21", {"us/top-free": filler(100, "u"), "gb/top-free": filler(100, "g")})
    after = snap("2026-10-22", {"us/top-free": ["hit"] + filler(99, "u"), "gb/top-free": ["hit"] + filler(99, "g"),
                                "de/top-free": ["hit"] + filler(99, "d")})
    doc = charts.compute_movers(after, before, CFG)
    hit = doc["rising"][0]
    assert hit["app_id"] == "hit" and [m["country"] for m in hit["moves"]] == ["gb", "us"]
    assert any("de/top-free: no list in the previous snapshot" in n for n in doc["notes"])


def test_first_run_says_so_and_still_lists_cross_country():
    first = snap("2026-10-22", {"us/top-free": filler(100, "u"), "in/top-free": filler(100, "i")})
    doc = charts.compute_movers(first, None, CFG)
    assert doc["rising"] == [] and doc["previous_date"] is None
    assert any(n.startswith("No previous snapshot: this is the first run") for n in doc["notes"])
    assert "works_abroad_not_in_us" in doc and "us_hits_missing_in_india_sea" in doc


def test_works_abroad_but_not_in_the_us():
    feeds = {
        "us/top-free": ["global"] + filler(99, "u"),
        "gb/top-free": ["abroad", "global", "two"] + filler(97, "g"),
        "de/top-free": filler(10, "d") + ["abroad"] + filler(30, "d")[10:] + ["two"] + filler(60, "dd"),
        "in/top-free": filler(49, "i") + ["abroad", "two"] + filler(49, "i")[1:],   # 50th: still top 50
        "id/top-free": filler(100, "n"),
    }
    doc = charts.compute_movers(snap("2026-10-22", feeds), None, CFG)
    abroad = {e["app_id"]: e for e in doc["works_abroad_not_in_us"]}
    assert set(abroad) == {"abroad"}            # "two" is top 50 in only two countries; "global" charts in the US
    e = abroad["abroad"]
    assert [(t["country"], t["rank"]) for t in e["top_in"]] == [("de", 11), ("gb", 1), ("in", 50)]
    assert e["us_rank"] is None and e["us_checked"] == [charts.FEED.format(country="us", chart="top-free")]
    assert all(t["source"].startswith("https://rss.marketingtools.apple.com/api/v2/") for t in e["top_in"])


def test_us_paid_chart_counts_as_charting_in_the_us():
    feeds = {"us/top-free": filler(100, "u"), "us/top-paid": ["abroad"],
             "gb/top-free": ["abroad"], "de/top-free": ["abroad"], "in/top-free": ["abroad"]}
    doc = charts.compute_movers(snap("2026-10-22", feeds), None, {**CFG, "charts": ["top-free", "top-paid"]})
    assert doc["works_abroad_not_in_us"] == []


def test_us_hits_missing_in_india_and_southeast_asia():
    feeds = {
        "us/top-free": ["everywhere", "us-only", "in-only"] + filler(47, "u") + ["us-51st"],
        "in/top-free": ["everywhere", "in-only"] + filler(98, "i"),
        "id/top-free": ["everywhere"] + filler(99, "n"),
        "sg/top-free": filler(100, "s"),
        "my/top-free": filler(100, "m"),
    }
    doc = charts.compute_movers(snap("2026-10-22", feeds), None, CFG)
    gaps = doc["us_hits_missing_in_india_sea"]
    assert [g["app_id"] for g in gaps][:1] == ["us-only"]
    assert "everywhere" not in {g["app_id"] for g in gaps} and "in-only" not in {g["app_id"] for g in gaps}
    assert "us-51st" not in {g["app_id"] for g in gaps}   # only the US top 50
    g = gaps[0]
    assert g["us_rank"] == 2 and g["missing_in"] == ["in", "id", "sg", "my"] and len(g["checked"]) == 4


def test_failed_feeds_are_noted_and_lists_skipped_when_needed():
    feeds = {"in/top-free": filler(100, "i"), "gb/top-free": ["x"], "de/top-free": ["x"], "id/top-free": ["x"]}
    doc = charts.compute_movers(snap("2026-10-22", feeds, failed=("us/top-free",)), None, CFG)
    assert doc["works_abroad_not_in_us"] == [] and doc["us_hits_missing_in_india_sea"] == []
    assert any("us/top-free" in n for n in doc["notes"]) and any("No US chart loaded" in n for n in doc["notes"])


def test_run_keeps_dated_snapshots_and_compares_with_the_day_before(tmp_path):
    from datetime import date as d

    ids = [str(100000 + i) for i in range(101)]   # Apple app ids are digits
    day1 = {"us": ids[:100], "in": ids[:100]}
    day2 = {"us": [ids[100]] + ids[:99], "in": ids[:100]}   # one new app in the US
    now = {"lists": day1}

    def fetcher(url, **kw):
        country = url.split("/v2/")[1].split("/")[0]
        return json.dumps({"feed": {"country": country, "updated": "x", "results": [
            {"id": i, "name": f"App {i}", "artistName": "m", "url": f"https://apps.apple.com/{country}/app/id{i}"}
            for i in now["lists"][country]]}}).encode()

    cfg = {"countries": ["us", "in"], "charts": ["top-free"]}
    state, out = tmp_path / "state", tmp_path / "run"
    st = charts.run(out, fetcher, cfg, state, today=d(2026, 10, 21))
    assert st["previous"] is None and st["ok"] == 2 and (state / "charts" / "2026-10-21.json").exists()
    first = json.loads((out / "chart-movers.json").read_text())
    assert first["previous"] is None and first["rising"] == [] and "first run" in first["notes"][0]
    assert first["snapshot"] == {"date": "2026-10-21", "file": str(state / "charts" / "2026-10-21.json"), "feeds_ok": 2,
                                 "feeds": 2, "failed": {}}
    now["lists"] = day2
    st = charts.run(out, fetcher, cfg, state, today=d(2026, 10, 22))
    doc = json.loads((out / "chart-movers.json").read_text())
    assert st["previous"] == "2026-10-21" and doc["previous"]["date"] == "2026-10-21"
    assert [e["app_id"] for e in doc["rising"]] == [ids[100]]
    # a rerun on the same day still compares with the day before, not with itself
    st = charts.run(out, fetcher, cfg, state, today=d(2026, 10, 22))
    assert st["previous"] == "2026-10-21" and st["rising"] == 1
    # snapshots older than keep_days are pruned
    (state / "charts" / "2026-01-01.json").write_text("{}")
    charts.run(out, fetcher, cfg, state, today=d(2026, 10, 22))
    assert not (state / "charts" / "2026-01-01.json").exists()
    assert "summary" not in doc and charts.summary_line(st).startswith("chart movers: 2/2 feeds; rising 1 (vs 2026-10-21)")


def test_state_dir_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("KEEPING_UP_SV_STATE", str(tmp_path / "x"))
    assert charts.state_dir() == tmp_path / "x"
    monkeypatch.delenv("KEEPING_UP_SV_STATE")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert charts.state_dir() == tmp_path / "xdg" / "keeping-up-sv"


# ---------------------------------------------------------------- essays


def test_essay_feeds_are_opinion_and_blocked_ones_stay_off():
    by_id = {s["id"]: s for s in json.loads(SKILL_SOURCES.read_text())["sources"]}
    for sid in ("sam-altman", "simon-willison", "elad-gil", "benedict-evans", "karpathy", "dwarkesh", "andrew-chen",
                "interconnected", "chinai", "sajith-pai"):
        s = by_id[sid]
        assert s["kind"] == "rss" and s["category"] == "analysis" and s["claim"] == "opinion", sid
        assert all(u.startswith("https://") for u in s.get("urls") or [s["url"]]), sid
    assert by_id["stripe-blog"]["claim"] == "confirmed"   # the company announcing its own news
    for sid in ("paul-graham", "naval", "stratechery"):
        assert by_id[sid]["enabled"] is False and by_id[sid]["disabled_reason"], sid
    ids = [s["id"] for s in by_id.values()]
    assert len(ids) == len(set(ids)) and all(len(i) <= 32 for i in ids)
    enabled = [s for s in by_id.values() if s.get("enabled", True)]
    assert len(enabled) <= 80   # the API takes at most 80 source statuses per run


ESSAY_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?><feed xml:lang="en-US" xmlns="http://www.w3.org/2005/Atom">
<entry><published>2026-10-21T22:55:13Z</published><updated>2026-10-22T19:13:05Z</updated>
<link rel="alternate" type="text/html" href="https://blog.example.com/2279512"/><title>-</title>
<content type="html">&lt;p&gt;A photo post with no real title.&lt;/p&gt;</content></entry>
<entry><published>2026-10-21T16:00:00Z</published><link rel="alternate" type="text/html" href="https://blog.example.com/the-firm-as-a-mind"/>
<title>The firm as a mind: what superintelligent companies do with pricing</title>
<content type="html">&lt;p&gt;Companies that learn from every transaction will price like a market of one.&lt;/p&gt;</content></entry>
</feed>"""


def test_an_essay_feed_skips_untitled_posts(monkeypatch):
    monkeypatch.setattr(collect, "fetch", lambda url, **kw: ESSAY_ATOM)
    src = {"id": "essay", "name": "An Operator", "kind": "rss", "url": "x", "weight": 12, "category": "analysis", "claim": "opinion"}
    cands, fetched = collect.collect_rss(src, *WINDOW)
    assert fetched == 2 and [c["url"] for c in cands] == ["https://blog.example.com/the-firm-as-a-mind"]
    assert cands[0]["claim_status"] == "opinion" and cands[0]["excerpt"].startswith("Companies that learn")


# ---------------------------------------------------------------- 小红书 and X (optional, login-gated)

import ingest  # noqa: E402
import social_login  # noqa: E402

DOCTOR_WARN = {
    "xiaohongshu": {"status": "warn", "backends": ["OpenCLI", "xiaohongshu-mcp", "xhs-cli (xiaohongshu-cli)"], "active_backend": None},
    "twitter": {"status": "warn", "backends": ["twitter-cli", "OpenCLI", "bird CLI (legacy)"], "active_backend": None},
}
DOCTOR_OK = {
    "xiaohongshu": {"status": "ok", "backends": ["OpenCLI"], "active_backend": "OpenCLI"},
    "twitter": {"status": "ok", "backends": ["twitter-cli", "OpenCLI"], "active_backend": "OpenCLI"},
}
XHS_SRC = {"id": "xiaohongshu", "name": "小红书 (needs your login)", "kind": "login", "platform": "xiaohongshu",
           "keywords": ["AI工具", "出海"], "limit": 10, "search_args": ["--publish-time", "day"], "weight": 6,
           "filter": False, "category": "discussion", "claim": "unverified"}
X_SRC = {**XHS_SRC, "id": "x-search", "name": "X search (needs your login)", "platform": "twitter", "keywords": ["MRR min_faves:200"],
         "search_args": []}
NOW = datetime(2026, 10, 22, 6, tzinfo=timezone.utc)


def test_the_gate_follows_agent_reach_doctor():
    assert social_login.decide(DOCTOR_OK, "xiaohongshu", False)[0] == "run"
    action, why = social_login.decide(DOCTOR_WARN, "xiaohongshu", False)
    assert action == "skip" and why.startswith("skipped: needs login (run agent-reach configure)") and "--login-sources" in why
    assert social_login.decide(DOCTOR_WARN, "twitter", True)[0] == "probe"
    assert social_login.decide({"twitter": {"status": "off", "backends": ["OpenCLI"]}}, "twitter", True)[0] == "skip"
    other = {"twitter": {"status": "ok", "backends": ["twitter-cli", "OpenCLI"], "active_backend": "twitter-cli"}}
    assert social_login.decide(other, "twitter", True) == (
        "skip", "skipped: needs login (run agent-reach configure); doctor's active backend is twitter-cli, "
                "and this step reads only through the OpenCLI bridge")
    assert social_login.decide(None, "twitter", True)[1].startswith("skipped: agent-reach is not installed")
    assert social_login.decide({"_error": "boom"}, "twitter", False)[0] == "skip"
    for _, why in (social_login.decide(DOCTOR_WARN, p, False) for p in ("xiaohongshu", "twitter")):
        assert len(why) <= 280   # fits the edition's error field


def test_counts_and_times_as_the_platforms_show_them():
    assert [social_login.count(v) for v in ("1.2万", "3.4w", "1.5K", "2M", "1,234", "10万+", 77, "", "n/a", True)] == \
        [12000, 34000, 1500, 2000000, 1234, 100000, 77, None, None, None]
    w = social_login.when
    assert w("2天前", NOW) == NOW - timedelta(days=2) and w("3小时前", NOW) == NOW - timedelta(hours=3)
    assert w("2h", NOW) == NOW - timedelta(hours=2) and w("刚刚", NOW) == NOW
    assert w("昨天 12:30", NOW) == datetime(2026, 10, 21, 4, 30, tzinfo=timezone.utc)      # Beijing time
    assert w("10-21", NOW) == datetime(2026, 10, 21, 4, tzinfo=timezone.utc)
    assert w("12-30", NOW).year == 2025                                                   # a future MM-DD is last year
    assert w("Wed Oct 21 16:00:00 +0000 2026", NOW) == datetime(2026, 10, 21, 16, tzinfo=timezone.utc)
    assert w("2026-10-21T19:30:00.000Z", NOW) == datetime(2026, 10, 21, 19, 30, tzinfo=timezone.utc)
    assert w("1792700000", NOW).year == 2026 and w("sometime", NOW) is None and w(None, NOW) is None


def test_xiaohongshu_results_become_candidates_without_the_session_token():
    rows = social_login.rows(fixture("opencli_xiaohongshu_search.json").decode())
    cands = [social_login.xhs_candidate(XHS_SRC, r, "AI工具", NOW) for r in rows]
    first, second, old, none = cands
    assert none is None
    assert first["url"] == "https://www.xiaohongshu.com/explore/6718a1b2000000001b012345"     # no xsec_token
    assert "xsec_token" in first["extra"]["open_url"] and first["extra"]["keyword"] == "AI工具"
    assert first["source_name"] == "小红书" and first["engagement"] == {"likes": 12000} and first["relevant"]
    assert first["claim_status"] == "unverified" and first["category"] == "discussion"
    assert first["published_at"] == (NOW - timedelta(days=2)).isoformat()
    assert second["engagement"] == {"likes": 856}
    assert old["published_at"].startswith("2025-03-01")
    assert social_login.rows('{"data": [{"title": "x"}]}') == [{"title": "x"}]
    with pytest.raises(collect.SourceError):
        social_login.rows("Please log in")


def test_x_results_become_embeddable_candidates():
    rows = social_login.rows(fixture("opencli_twitter_search.json").decode())
    first, second, old = (social_login.x_candidate(X_SRC, r, "MRR", NOW) for r in rows)
    assert first["url"] == "https://x.com/examplefounder/status/1850000000000000001" and first["embed_url"] == first["url"]
    assert svlib.detect_embed(first["url"]) == ("x", "1850000000000000001")
    assert first["title"].startswith("We just hit $1M ARR, 14 months after launch. Thanks")
    assert first["engagement"] == {"likes": 4100, "views": 380000} and first["author"] == "examplefounder"
    assert second["url"] == "https://x.com/another_maker/status/1850000000000000002"          # built from id + handle
    assert second["engagement"] == {"likes": 950}
    assert old["published_at"].startswith("2023-01-02")


def fake_cli(monkeypatch, report, answers):
    """Patch doctor and the opencli calls; returns the list of commands run."""
    calls = []
    monkeypatch.setattr(social_login, "doctor", lambda: report)
    monkeypatch.setattr(social_login, "_bin", lambda name, env: f"/bin/{name}")

    def run(args, timeout):
        calls.append(args)
        return answers.pop(0)
    monkeypatch.setattr(social_login, "run_cmd", run)
    return calls


def test_skipped_when_doctor_cannot_confirm_a_login(monkeypatch):
    calls = fake_cli(monkeypatch, DOCTOR_WARN, [])
    status, cands = collect.run_source(XHS_SRC, *WINDOW, False)
    assert calls == [] and cands == []          # nothing ran in the founder's browser
    assert status["ok"] is False and status["skipped"] is True
    assert status["error"].startswith("skipped: needs login (run agent-reach configure)")


def test_runs_searches_one_at_a_time_when_doctor_says_ok(monkeypatch):
    xhs = fixture("opencli_xiaohongshu_search.json").decode()
    calls = fake_cli(monkeypatch, DOCTOR_OK, [(0, xhs, ""), (0, "[]", "")])
    cands, fetched = social_login.collect_login(XHS_SRC, NOW - timedelta(hours=48), NOW, False, now=NOW, pause=0)
    assert fetched == 4 and [c["url"].rsplit("/", 1)[1] for c in cands] == ["6718a1b2000000001b012345", "6718a1b2000000001b0abcde"]
    assert calls[0] == ["/bin/opencli", "xiaohongshu", "search", "AI工具", "--limit", "10", "--publish-time", "day",
                        "--window", "background", "-f", "json"]
    assert calls[1][3] == "出海"


def test_x_search_adds_the_window_start(monkeypatch):
    calls = fake_cli(monkeypatch, DOCTOR_OK, [(0, fixture("opencli_twitter_search.json").decode(), "")])
    cands, _ = social_login.collect_login(X_SRC, NOW - timedelta(hours=48), NOW, False, now=NOW, pause=0)
    assert calls[0][3] == "MRR min_faves:200 since:2026-10-20"
    assert len(cands) == 2                      # the 2023 post is outside the window


def test_probe_skips_on_an_empty_or_failed_first_search(monkeypatch):
    fake_cli(monkeypatch, DOCTOR_WARN, [(0, "[]", "")])
    with pytest.raises(social_login.Skipped, match="^skipped: needs login .*returned nothing"):
        social_login.collect_login(X_SRC, *WINDOW, True, now=NOW, pause=0)
    fake_cli(monkeypatch, DOCTOR_WARN, [(1, "", "Not logged in")])
    with pytest.raises(social_login.Skipped, match="login check failed"):
        social_login.collect_login(X_SRC, *WINDOW, True, now=NOW, pause=0)
    fake_cli(monkeypatch, DOCTOR_WARN, [(0, fixture("opencli_twitter_search.json").decode(), "")])
    cands, _ = social_login.collect_login(X_SRC, NOW - timedelta(hours=48), NOW, True, now=NOW, pause=0)
    assert len(cands) == 2


def test_a_skipped_login_source_does_not_make_the_run_partial():
    totals = {"inserted": 3, "updated": 0, "merged": 0, "rejected": 0}
    ok = {"source": "techcrunch", "ok": True}
    skipped = {"source": "xiaohongshu", "ok": False, "skipped": True, "error": social_login.NEEDS_LOGIN}
    failed = {"source": "reddit", "ok": False, "error": "HTTP 429 from Reddit"}
    assert ingest.run_status([ok, skipped], totals, []) == "complete"
    assert ingest.run_status([ok, skipped, failed], totals, []) == "partial"
    assert ingest.run_status([ok], {**totals, "inserted": 0}, []) == "failed"


def test_configured_login_sources():
    login = {s["id"]: s for s in configured("login")}
    assert login["xiaohongshu"]["platform"] == "xiaohongshu" and "出海" in login["xiaohongshu"]["keywords"]
    assert login["x-search"]["platform"] == "twitter"
    assert all(s["claim"] == "unverified" and s["keywords"] for s in login.values())
