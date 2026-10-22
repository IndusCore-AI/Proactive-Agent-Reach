"""Tests for the skill's mover commands (ingest.py movers / link / archive):
the file checks and the leak check. Standard library only; no network."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "aggregate-silicon-valley" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ingest  # noqa: E402


def mover(**kw):
    base = {
        "id": "example-robotics", "name": "Example Robotics", "kind": "company", "url": "https://example.com",
        "one_liner": "Robot arms for small kitchens.",
        "traction": [{"label": "Restaurants live", "value": "120", "source_url": "https://example.com/blog", "as_of": "2026-10-01"}],
        "notes": {"take": "A private take.", "learn": "A private lesson.", "localize": "A private market note."},
        "item_urls": ["https://example.com/story"],
    }
    base.update(kw)
    return base


def test_a_complete_mover_has_no_problems():
    assert ingest.mover_problems(mover()) == []
    assert ingest.mover_problems(mover(notes=None, traction=[], item_urls=[])) == []


@pytest.mark.parametrize("bad,expected", [
    (mover(traction=[{"label": "Users", "value": "10k", "as_of": "2026-10-01"}]), "needs a source_url"),
    (mover(traction=[{"label": "Users", "value": "10k", "source_url": "http://example.com", "as_of": "2026-10-01"}]), "needs a source_url"),
    (mover(traction=[{"label": "Users", "value": "10k", "source_url": "https://example.com"}]), "as_of"),
    (mover(traction=[{"label": "U", "value": "1", "source_url": "https://example.com", "as_of": "2026-10-01"}] * 9), "at most 8"),
    (mover(id="Example Robotics"), "lowercase slug"),
    (mover(id="unlock"), "not unlock/lock/updates"),
    (mover(kind="person"), "kind must be"),
    (mover(take="belongs under notes"), "unknown fields ['take']"),
    (mover(notes={"takes": "typo"}), "notes has unknown fields"),
    (mover(notes={"take": "x" * 1501}), "notes.take is over 1500"),
    (mover(one_liner="x" * 201), "one_liner is over 200"),
    (mover(claim_status="opinion"), "claim_status"),
    (mover(item_urls=[f"https://example.com/{i}" for i in range(51)]), "at most 50"),
    ({"id": "example-robotics"}, "missing name"),
])
def test_problems_are_caught_before_sending(bad, expected):
    assert any(expected in p for p in ingest.mover_problems(bad)), ingest.mover_problems(bad)


def test_load_movers_refuses_a_bad_file(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"movers": [mover(), mover(id="example-notes-app", name="Example Notes App", kind="app")]}))
    assert [m["id"] for m in ingest.load_movers(good)] == ["example-robotics", "example-notes-app"]
    dup = tmp_path / "dup.json"
    dup.write_text(json.dumps({"movers": [mover(), mover()]}))
    with pytest.raises(SystemExit, match="more than once"):
        ingest.load_movers(dup)
    sourceless = tmp_path / "sourceless.json"
    sourceless.write_text(json.dumps([mover(traction=[{"label": "Users", "value": "1", "as_of": "2026-10-01"}])]))
    with pytest.raises(SystemExit, match="no source, no line"):
        ingest.load_movers(sourceless)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"movers": []}))
    with pytest.raises(SystemExit):
        ingest.load_movers(empty)


def test_leak_check_finds_note_text_in_a_page():
    notes = ingest.note_texts([mover(notes={"take": "We could copy the onboarding flow &amp; pricing page for India within a quarter."})])
    assert len(notes) == 1
    clean = "<html><h1>Example Robotics</h1><p>Robot arms for small kitchens.</p></html>"
    assert ingest.leaked(clean, notes) == []
    # escaped, re-wrapped, or only part of it shown: still caught
    page = "<p>We could copy the onboarding flow &amp;amp; pricing\n   page for India</p>"
    assert ingest.leaked(page, notes)
    assert ingest.leaked("<p>Hello</p>", ["short"]) == []
    assert ingest.leaked("<p>a short note</p>", ["short note"]) == ["short note"]


def test_subcommands_are_dispatched_before_the_edition_parser(monkeypatch):
    seen = {}
    monkeypatch.setitem(ingest.SUBCOMMANDS, "link", lambda argv: seen.setdefault("link", argv))
    monkeypatch.setattr(sys, "argv", ["ingest.py", "link", "example-robotics", "https://example.com/story"])
    ingest.main()
    assert seen["link"] == ["example-robotics", "https://example.com/story"]


SCORE = {"lines": {"demand": 10, "problem": 7, "fit": 12, "wedge": 6, "market": 7, "future": 10, "moat": 5, "whitespace": 3},
         "market": "Example market", "verdict": "A private verdict line."}


def test_a_scored_proposal_has_no_problems():
    assert ingest.mover_problems(mover(status="proposed", notes={"take": "x", "score": SCORE})) == []
    assert ingest.notes_problems({"score": SCORE}) == []
    assert ingest.notes_problems({"score": {**SCORE, "total": 60}}) == []


@pytest.mark.parametrize("bad,expected", [
    ({**SCORE, "lines": {**SCORE["lines"], "demand": 26}}, "from 0 to 25"),
    ({**SCORE, "lines": {"demand": 1}}, "must be exactly"),
    ({**SCORE, "total": 99}, "not the sum"),
    ({**SCORE, "market": ""}, "name the target market"),
    ({**SCORE, "stars": 5}, "unknown fields"),
])
def test_bad_scores_are_caught(bad, expected):
    assert any(expected in p for p in ingest.notes_problems({"score": bad}))


def test_status_and_reserved_ids():
    assert any("status must be" in p for p in ingest.mover_problems(mover(status="live")))
    assert any("not unlock/lock/updates" in p for p in ingest.mover_problems(mover(id="updates")))


def test_the_leak_check_covers_a_score_verdict():
    texts = ingest.note_texts([mover(notes={"take": "A take.", "score": SCORE})])
    assert "A private verdict line." in texts and "A take." in texts
