"""Tests for the skill's research command (ingest.py research): the file
checks, what it sends, and how it verifies. Standard library only; no network."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "aggregate-silicon-valley" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ingest  # noqa: E402

LINES = {"demand": 0, "problem": 5, "fit": 13, "wedge": 5, "market": 6, "future": 10, "moat": 6, "whitespace": 3}  # 48


def run(**kw):
    base = {
        "id": "2026-10-22-example-lead", "title": "Example lead", "run_date": "2026-10-22", "outcome": "makes_list",
        "verdict": "Best 48", "summary": "A private summary of the lead.", "method": "Read the app charts.",
        "findings": [{"title": "The lead", "text": "A private finding about the lead."},
                     {"group": "How they grew", "text": "Reddit for the first users, then search."}],
        "sources": [{"label": "Example source", "url": "https://example.com/source"}],
        "refs": ["03-example.md", "k:1"], "position": 1,
        "ideas": [
            {"idea": "Example -> a localized version", "market": "India", "total": 48, "lines": LINES, "mover_id": "example-robotics"},
            {"idea": "A weaker idea", "market": "Bangladesh", "total": 31, "note": "Platforms ship it free."},
        ],
    }
    base.update(kw)
    return base


def test_a_complete_run_has_no_problems():
    assert ingest.research_problems(run()) == []
    assert ingest.research_problems(run(outcome="no", ideas=[], findings=[], sources=[], refs=[])) == []
    assert ingest.research_problems(run(outcome="below_cutoff", ideas=[run()["ideas"][1]])) == []


@pytest.mark.parametrize("bad,expected", [
    (run(id="Example Lead"), "lowercase slug"),
    (run(title=""), "title must be text (required)"),
    (run(run_date="22 Oct"), "run_date must be YYYY-MM-DD"),
    (run(outcome="maybe"), "outcome must be one of"),
    (run(outcome="makes_list", ideas=[run()["ideas"][1]]), "needs an idea at 40 or more"),
    (run(outcome="below_cutoff"), "all under 40"),
    (run(ideas=[{**run()["ideas"][0], "total": 50}]), "is not the sum of the lines"),
    (run(ideas=[{**run()["ideas"][0], "lines": {**LINES, "demand": 30}, "total": 78}]), "within each line's maximum"),
    (run(ideas=[{**run()["ideas"][0], "lines": {"demand": 0}}]), "lines must be exactly"),
    (run(ideas=[{**run()["ideas"][0], "score": 48}]), "unknown fields"),
    (run(findings=[{"text": "<b>bold</b> claim"}]), "markup"),
    (run(findings=[{"text": "x"}] * 21), "at most 20"),
    (run(sources=[{"label": "Plain http", "url": "http://example.com"}]), "https url"),
    (run(take="a mover field"), "unknown fields"),
])
def test_problems_are_caught_before_sending(bad, expected):
    problems = ingest.research_problems(bad)
    assert any(expected in p for p in problems), problems


def test_load_research_refuses_a_bad_file(tmp_path):
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"runs": [run(), run()]}))
    with pytest.raises(SystemExit, match="appears more than once"):
        ingest.load_research(f)
    f.write_text(json.dumps({"runs": []}))
    with pytest.raises(SystemExit, match="1 to 20 runs"):
        ingest.load_research(f)


def test_research_is_a_reserved_mover_id():
    assert "research" in ingest.RESERVED_MOVER_IDS


def test_research_sends_verifies_and_checks_the_locked_page(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_call(method, url, token=None, body=None, timeout=60):
        calls.append((method, url.split("?")[0], body))
        if method == "POST":
            return 200, {"inserted": 1, "updated": 0, "rejected": 0,
                         "results": [{"index": 0, "id": run()["id"], "outcome": "inserted", "ideas": 2, "unlinked": []}]}
        if url.endswith("/api/ingest/research"):
            return 200, {"runs": [{"id": run()["id"], "ideas": 2, "best": 48, "verdict": "Best 48", "run_date": "2026-10-22"}]}
        return 200, "<html><p>This page is for the founders.</p></html>"   # the locked page

    monkeypatch.setattr(ingest, "call", fake_call)
    monkeypatch.setattr(ingest, "connection", lambda: ("https://example.invalid/sv", "token"))
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"runs": [run()]}))
    with pytest.raises(SystemExit) as done:
        ingest.cmd_research([str(f)])
    report = json.loads(capsys.readouterr().out)
    assert done.value.code == 0 and report["db_verified"] and report["locked_page_clean"]
    assert [c[:2] for c in calls] == [("POST", "https://example.invalid/sv/api/ingest/research"),
                                      ("GET", "https://example.invalid/sv/api/ingest/research"),
                                      ("GET", "https://example.invalid/sv/movers/research")]
    assert calls[0][2] == {"runs": [run()]}


def test_a_leak_on_the_locked_page_fails_the_run(monkeypatch, tmp_path, capsys):
    def fake_call(method, url, token=None, body=None, timeout=60):
        if method == "POST":
            return 200, {"inserted": 1, "updated": 0, "rejected": 0, "results": [{"id": run()["id"], "outcome": "inserted"}]}
        if url.split("?")[0].endswith("/api/ingest/research"):
            return 200, {"runs": [{"id": run()["id"], "ideas": 2}]}
        return 200, "<p>A private finding about the lead.</p>"

    monkeypatch.setattr(ingest, "call", fake_call)
    monkeypatch.setattr(ingest, "connection", lambda: ("https://example.invalid/sv", "token"))
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"runs": [run()]}))
    with pytest.raises(SystemExit) as done:
        ingest.cmd_research([str(f)])
    assert done.value.code == 2 and json.loads(capsys.readouterr().out)["locked_page_problems"]
