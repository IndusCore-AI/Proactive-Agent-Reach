"""A whole collect.py run with every new source kind, from fixtures: YouTube,
Reddit through the polite fetcher, an essay feed, the login-gated 小红书 step
(skipped: no login) and the App Store chart movers. Then the curated file
path to ingest, to prove the local-only fields never reach the API.
Standard library only; no network."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "aggregate-silicon-valley" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import collect  # noqa: E402
import ingest  # noqa: E402
import social_login  # noqa: E402

ESSAY = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><published>2026-10-21T16:00:00Z</published><link rel="alternate" href="https://blog.example.com/firms-as-minds"/>
<title>Companies as minds: pricing when the firm knows everything</title>
<content type="html">&lt;p&gt;An essay on what changes when a company learns from every transaction.&lt;/p&gt;</content></entry></feed>"""


def router(url: str, **kw) -> bytes:
    if "youtube.com/feeds" in url:
        return (FIXTURES / "youtube_channel.xml").read_bytes()
    if "rss.marketingtools.apple.com" in url:
        country = url.split("/v2/")[1].split("/")[0]
        if country == "sg":
            raise collect.SourceError("HTTP 503 for rss.marketingtools.apple.com")
        doc = json.loads((FIXTURES / "apple_chart_us_top_free.json").read_text())
        doc["feed"]["country"] = country
        return json.dumps(doc).encode()
    if "samaltman" in url:
        return ESSAY
    raise AssertionError(f"unexpected fetch {url}")


class OneReddit:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return (FIXTURES / "reddit_top.xml").read_bytes()


@pytest.fixture
def run_dir(monkeypatch, tmp_path, capsys):
    reddit = OneReddit()
    monkeypatch.setattr(collect, "fetch", router)
    monkeypatch.setattr(collect, "REDDIT", reddit)
    monkeypatch.setattr(social_login, "doctor", lambda: {"xiaohongshu": {"status": "warn", "backends": ["OpenCLI"], "active_backend": None}})
    monkeypatch.setattr(social_login, "run_cmd", lambda *a, **k: pytest.fail("no search may run without a login"))
    monkeypatch.setenv("KEEPING_UP_SV_STATE", str(tmp_path / "state"))
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["collect.py", "--date", "2026-10-21", "--out", str(out),
                                      "--only", "yt-ycombinator,reddit-builders,sam-altman,xiaohongshu,charts"])
    collect.main()
    return out, reddit, capsys.readouterr().out


def test_a_full_run_writes_candidates_statuses_and_chart_movers(run_dir):
    out, reddit, printed = run_dir
    statuses = {s["source"]: s for s in json.loads((out / "sources.json").read_text())}
    assert set(statuses) == {"yt-ycombinator", "reddit-builders", "sam-altman", "xiaohongshu"}
    assert all(statuses[s]["ok"] for s in ("yt-ycombinator", "reddit-builders", "sam-altman"))
    assert statuses["xiaohongshu"]["skipped"] is True and statuses["xiaohongshu"]["ok"] is False
    assert statuses["xiaohongshu"]["error"].startswith("skipped: needs login (run agent-reach configure)")
    assert reddit.urls == ["https://www.reddit.com/r/SaaS+SideProject/top/.rss?t=day&limit=30"]

    cands = json.loads((out / "candidates.json").read_text())["candidates"]
    by_source = {}
    for c in cands:
        by_source.setdefault(c["source"], []).append(c)
    assert [c["url"] for c in by_source["yt-ycombinator"]] == ["https://www.youtube.com/watch?v=AbCdEfGhIj0"]
    assert {c["source_name"] for c in by_source["reddit-builders"]} == {"r/SaaS", "r/SideProject"}
    assert by_source["sam-altman"][0]["category"] == "analysis"
    assert cands == sorted(cands, key=lambda c: -c["score"])

    movers = json.loads((out / "chart-movers.json").read_text())
    assert movers["previous"] is None and movers["rising"] == []
    assert movers["snapshot"]["feeds_ok"] == 22 and set(movers["snapshot"]["failed"]) == {"sg/top-free", "sg/top-paid"}
    assert any("first run" in n for n in movers["notes"])
    assert "skip xiaohongshu" in printed and "chart movers: 22/24 feeds" in printed


def test_only_without_charts_skips_them(monkeypatch, tmp_path):
    monkeypatch.setattr(collect, "fetch", router)
    monkeypatch.setenv("KEEPING_UP_SV_STATE", str(tmp_path / "state"))
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["collect.py", "--date", "2026-10-21", "--out", str(out), "--only", "sam-altman"])
    collect.main()
    assert (out / "candidates.json").exists() and not (out / "chart-movers.json").exists()


def test_a_chart_crash_never_breaks_the_edition(monkeypatch, tmp_path, capsys):
    import charts

    monkeypatch.setattr(collect, "fetch", router)
    monkeypatch.setattr(charts, "run", lambda *a, **k: 1 / 0)
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["collect.py", "--date", "2026-10-21", "--out", str(out), "--only", "sam-altman,charts"])
    collect.main()
    assert (out / "candidates.json").exists()
    assert "chart movers: failed (ZeroDivisionError" in capsys.readouterr().out


def test_local_only_fields_never_reach_the_api(tmp_path):
    """A curated 小红书 note keeps its session token only in candidates.json:
    ingest sends a fixed set of fields, and `extra` is not one of them."""
    row = social_login.rows((FIXTURES / "opencli_xiaohongshu_search.json").read_text())[0]
    src = {"id": "xiaohongshu", "name": "小红书", "kind": "login", "platform": "xiaohongshu", "weight": 6,
           "category": "discussion", "claim": "unverified"}
    from datetime import datetime, timezone

    c = collect.prescore(social_login.xhs_candidate(src, row, "AI工具", datetime(2026, 10, 22, 6, tzinfo=timezone.utc)),
                         datetime(2026, 10, 22, 6, tzinfo=timezone.utc))
    assert "xsec_token" in c["extra"]["open_url"]
    f = tmp_path / "curated.json"
    f.write_text(json.dumps({"items": [c]}, ensure_ascii=False))
    sent = ingest.load_curated(f)
    assert "xsec_token" not in json.dumps(sent, ensure_ascii=False)
    assert set(sent[0]) <= {"url", "title", "source", "source_name", "category", "tags", "excerpt", "summary", "author",
                            "published_at", "claim_status", "funding", "embed_url", "mentions", "score", "score_detail",
                            "image_url", "image_kind"}
