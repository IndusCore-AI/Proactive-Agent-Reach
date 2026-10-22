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
    (mover(id="unlock"), "not unlock/lock"),
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
