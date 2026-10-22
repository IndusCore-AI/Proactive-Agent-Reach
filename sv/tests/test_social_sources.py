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
