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
