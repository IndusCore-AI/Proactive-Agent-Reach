#!/usr/bin/env python3
"""App Store chart movers: apps breaking out before the press writes about them.

  python3 charts.py [--out DIR] [--state DIR]

Reads Apple's public top-chart feeds (top free and top paid iPhone apps, top
100, one feed per country; no key), keeps a dated snapshot of every chart in
the skill's local state directory, compares it with the previous snapshot and
writes DIR/chart-movers.json with three lists:

  rising                          new to a country's top 100 since the last
                                  snapshot, or up RISE_PLACES or more places
  works_abroad_not_in_us          in the top 50 in 3+ other countries but in
                                  neither US top 100 (works abroad, missing in the US)
  us_hits_missing_in_india_sea    in a US top 50 but in no top 100 in India and
                                  Southeast Asia (a gap to localize)

Every entry carries its evidence: country, rank, previous rank, both snapshot
dates and the feed URL as its source. These are candidates for proposed
movers, never news items. The first run has no previous snapshot: it says so
and still writes the two cross-country lists.

State: $KEEPING_UP_SV_STATE, else $XDG_STATE_HOME/keeping-up-sv, else
~/.local/state/keeping-up-sv; snapshots are charts/YYYY-MM-DD.json (Pacific
date of the fetch), pruned after KEEP_DAYS. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

FEED = "https://rss.marketingtools.apple.com/api/v2/{country}/apps/{chart}/100/apps.json"
HOME = "us"
DEFAULTS = {
    "countries": ["us", "in", "gb", "es", "id", "au", "br", "de", "sg", "my", "ae", "sa"],
    "charts": ["top-free", "top-paid"],
    "rise_places": 25,          # "up 25+ places"
    "abroad_top": 50,           # top 50 abroad ...
    "abroad_min_countries": 3,  # ... in 3+ countries, in no US top 100
    "home_top": 50,             # US top 50 ...
    "localize_in": ["in", "id", "sg", "my"],   # ... in no top 100 here (India and Southeast Asia)
    "keep_days": 90,
}


def state_dir() -> Path:
    if os.environ.get("KEEPING_UP_SV_STATE"):
        return Path(os.environ["KEEPING_UP_SV_STATE"])
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "keeping-up-sv"


def settings(cfg: dict | None) -> dict:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (cfg or {}).items() if k in DEFAULTS})
    return out


# ---------------------------------------------------------------- reading the feeds


def parse_chart(raw: bytes) -> dict:
    """One Apple chart feed as {country, updated, apps: [{id, name, artist,
    url, released, rank}]}, ranks from 1 in feed order."""
    try:
        feed = json.loads(raw)["feed"]
        results = feed["results"]
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"not an Apple chart feed ({type(e).__name__})")
    apps = []
    for rank, r in enumerate(results, 1):
        if not isinstance(r, dict) or not str(r.get("id", "")).isdigit():
            continue
        apps.append({"id": str(r["id"]), "name": str(r.get("name", ""))[:200], "artist": str(r.get("artistName", ""))[:200],
                     "url": str(r.get("url", "")), "released": r.get("releaseDate"), "rank": rank})
    if not apps:
        raise ValueError("the chart is empty")
    return {"country": feed.get("country"), "updated": feed.get("updated"), "apps": apps}


def fetch_snapshot(cfg: dict, fetcher: Callable[..., bytes], today: date) -> dict:
    """Every configured chart, four at a time. A feed that fails is recorded
    with its error; the others still count."""
    keys = [(c, ch) for c in cfg["countries"] for ch in cfg["charts"]]

    def one(key: tuple[str, str]) -> tuple[str, dict]:
        country, chart = key
        url = FEED.format(country=country, chart=chart)
        try:
            return f"{country}/{chart}", {"url": url, **parse_chart(fetcher(url, tries=2))}
        except Exception as e:  # one bad feed never stops the rest
            return f"{country}/{chart}", {"url": url, "error": str(e)[:200] or type(e).__name__}

    with ThreadPoolExecutor(max_workers=4) as pool:
        feeds = dict(pool.map(one, keys))
    return {"date": today.isoformat(), "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "feeds": feeds}


# ---------------------------------------------------------------- snapshots


def save_snapshot(snap: dict, state: Path, keep_days: int) -> Path:
    folder = state / "charts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{snap['date']}.json"
    path.write_text(json.dumps(snap, ensure_ascii=False))
    cutoff = date.fromisoformat(snap["date"]) - timedelta(days=keep_days)
    for old in folder.glob("*.json"):
        try:
            if date.fromisoformat(old.stem) < cutoff:
                old.unlink()
        except ValueError:
            continue
    return path


def load_previous(state: Path, today: date) -> tuple[dict | None, Path | None]:
    """The newest snapshot from before today (a rerun on the same day compares
    with the day before, not with itself)."""
    folder = state / "charts"
    dated = []
    for p in folder.glob("*.json") if folder.exists() else []:
        try:
            d = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if d < today:
            dated.append((d, p))
    for _, p in sorted(dated, reverse=True):
        try:
            return json.loads(p.read_text()), p
        except (OSError, ValueError):
            continue
    return None, None


# ---------------------------------------------------------------- the diff


def _ok(snap: dict) -> dict[str, dict]:
    return {k: f for k, f in snap.get("feeds", {}).items() if "apps" in f}


def _present(feeds: dict[str, dict], country: str) -> set[str] | None:
    """App ids in any of the country's charts; None when none of them loaded."""
    lists = [f for k, f in feeds.items() if k.split("/")[0] == country]
    if not lists:
        return None
    return {a["id"] for f in lists for a in f["apps"]}


def _app(a: dict) -> dict:
    return {"app_id": a["id"], "name": a["name"], "artist": a["artist"], "url": a["url"], "released": a.get("released")}


def compute_movers(current: dict, previous: dict | None, cfg: dict | None = None) -> dict:
    """The three lists, from two snapshots (or one on the first run). Pure:
    no network, no files."""
    cfg = settings(cfg)
    feeds, notes = _ok(current), []
    failed = sorted(k for k, f in current.get("feeds", {}).items() if "apps" not in f)
    if failed:
        notes.append(f"{len(failed)} chart feed(s) did not load and are left out: {', '.join(failed)}.")

    # 1. rising: new to the top 100, or up rise_places or more
    rising: dict[tuple[str, str], dict] = {}
    if previous is None:
        notes.append("No previous snapshot: this is the first run, so there is no rising list yet. "
                     "The next run compares against this one. The cross-country lists do not need one.")
    else:
        before = _ok(previous)
        for key, feed in sorted(feeds.items()):
            country, chart = key.split("/")
            if key not in before:
                notes.append(f"{key}: no list in the previous snapshot to compare with.")
                continue
            prev_rank = {a["id"]: a["rank"] for a in before[key]["apps"]}
            for a in feed["apps"]:
                p = prev_rank.get(a["id"])
                if p is not None and p - a["rank"] < cfg["rise_places"]:
                    continue
                entry = rising.setdefault((a["id"], chart), {**_app(a), "chart": chart, "moves": []})
                if country == HOME:
                    entry.update(name=a["name"], url=a["url"])
                entry["moves"].append({"country": country, "rank": a["rank"], "previous_rank": p,
                                       "places_up": None if p is None else p - a["rank"],
                                       "date": current["date"], "previous_date": previous.get("date"), "source": feed["url"]})

    # 2. works abroad, missing in the US
    home_present = _present(feeds, HOME)
    abroad: list[dict] = []
    if home_present is None:
        notes.append("No US chart loaded, so the 'works abroad, not in the US' list is skipped.")
    else:
        home_sources = [f["url"] for k, f in sorted(feeds.items()) if k.startswith(HOME + "/")]
        for chart in cfg["charts"]:
            tops: dict[str, dict] = {}
            for key, feed in sorted(feeds.items()):
                country, ch = key.split("/")
                if ch != chart or country == HOME:
                    continue
                for a in feed["apps"]:
                    if a["rank"] <= cfg["abroad_top"] and a["id"] not in home_present:
                        e = tops.setdefault(a["id"], {**_app(a), "chart": chart, "top_in": []})
                        e["top_in"].append({"country": country, "rank": a["rank"], "source": feed["url"]})
            for e in tops.values():
                if len(e["top_in"]) >= cfg["abroad_min_countries"]:
                    e.update(us_rank=None, us_checked=home_sources, date=current["date"])
                    abroad.append(e)

    # 3. US hits missing in India and Southeast Asia
    gaps: list[dict] = []
    checked = {c: _present(feeds, c) for c in cfg["localize_in"]}
    loaded = [c for c, ids in checked.items() if ids is not None]
    if home_present is None or "in" not in loaded or len(loaded) < 2:
        notes.append("Not enough charts loaded (the US, India and at least one Southeast Asian country) "
                     "for the 'US hits missing in India and Southeast Asia' list; it is skipped.")
    else:
        if len(loaded) < len(checked):
            notes.append(f"Localize list checked only {', '.join(loaded)} (the other charts did not load).")
        seen: set[str] = set()
        for key, feed in sorted(feeds.items()):
            country, chart = key.split("/")
            if country != HOME:
                continue
            for a in feed["apps"]:
                if a["rank"] > cfg["home_top"] or a["id"] in seen:
                    continue
                if all(a["id"] not in checked[c] for c in loaded):
                    seen.add(a["id"])
                    gaps.append({**_app(a), "chart": chart, "us_rank": a["rank"], "source": feed["url"],
                                 "missing_in": loaded, "date": current["date"],
                                 "checked": [f["url"] for k, f in sorted(feeds.items()) if k.split("/")[0] in loaded]})

    rising_list = sorted(rising.values(), key=lambda e: (-len(e["moves"]), min(m["rank"] for m in e["moves"])))
    abroad.sort(key=lambda e: (-len(e["top_in"]), min(t["rank"] for t in e["top_in"])))
    gaps.sort(key=lambda e: e["us_rank"])
    return {
        "snapshot_date": current["date"],
        "previous_date": previous.get("date") if previous else None,
        "notes": notes,
        "rules": {
            "rising": f"new to a country's top 100 since the previous snapshot, or up {cfg['rise_places']}+ places",
            "works_abroad_not_in_us": f"top {cfg['abroad_top']} in {cfg['abroad_min_countries']}+ countries, in no US top 100 (free or paid)",
            "us_hits_missing_in_india_sea": f"US top {cfg['home_top']}, in no top 100 in {', '.join(cfg['localize_in'])}",
        },
        "rising": rising_list,
        "works_abroad_not_in_us": abroad,
        "us_hits_missing_in_india_sea": gaps,
    }


# ---------------------------------------------------------------- run


def run(out_dir: Path, fetcher: Callable[..., bytes], cfg: dict | None = None, state: Path | None = None,
        today: date | None = None) -> dict:
    """Fetch, snapshot, diff and write DIR/chart-movers.json. Returns a short
    status for the caller to print."""
    cfg = settings(cfg)
    state = state or state_dir()
    if today is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import svlib  # noqa: E402

        today = svlib.today_pt()
    current = fetch_snapshot(cfg, fetcher, today)
    ok = len(_ok(current))
    previous, prev_path = load_previous(state, today)
    doc = compute_movers(current, previous, cfg)
    path = save_snapshot(current, state, cfg["keep_days"]) if ok else None
    if not ok:
        doc["notes"].insert(0, "No chart feed loaded; no snapshot was saved.")
    doc = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "snapshot": {"date": current["date"], "file": str(path) if path else None, "feeds_ok": ok,
                        "feeds": len(current["feeds"]),
                        "failed": {k: f["error"] for k, f in current["feeds"].items() if "error" in f}},
           "previous": {"date": previous.get("date"), "file": str(prev_path)} if previous else None,
           **{k: v for k, v in doc.items() if k not in ("snapshot_date", "previous_date")}}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "chart-movers.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    return {"ok": ok, "feeds": len(current["feeds"]), "previous": doc["previous"]["date"] if previous else None,
            "rising": len(doc["rising"]), "abroad": len(doc["works_abroad_not_in_us"]),
            "gaps": len(doc["us_hits_missing_in_india_sea"]), "path": str(out_dir / "chart-movers.json")}


def summary_line(st: dict) -> str:
    vs = f"vs {st['previous']}" if st["previous"] else "first snapshot, nothing to compare yet"
    return (f"chart movers: {st['ok']}/{st['feeds']} feeds; rising {st['rising']} ({vs}); works abroad not in US "
            f"{st['abroad']}; US hits missing in India/SEA {st['gaps']} -> {st['path']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, help="directory for chart-movers.json (default: <tmp>/keeping-up-sv/charts)")
    ap.add_argument("--state", type=Path, help="state directory (default: see above)")
    args = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from collect import SKILL_DIR, fetch  # noqa: E402

    cfg = json.loads((SKILL_DIR / "sources.json").read_text()).get("charts")
    out = args.out or Path(tempfile.gettempdir()) / "keeping-up-sv" / "charts"
    print(summary_line(run(out, fetch, cfg, args.state)))


if __name__ == "__main__":
    main()
