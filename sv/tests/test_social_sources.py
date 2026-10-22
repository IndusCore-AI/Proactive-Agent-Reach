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
