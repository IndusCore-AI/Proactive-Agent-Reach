#!/usr/bin/env python3
"""Persist a curated edition and prove it landed.

  python3 ingest.py --date YYYY-MM-DD --curated curated.json --sources sources.json
  python3 ingest.py --check                     # token + API reachability only

Talks only to the public site's ingest endpoint (default
https://induscore.site/sv/api/ingest), which forwards to the VM API with your
own ingest token. Steps: start a run, send items in batches, finish the run
with every source's status, then verify (1) the database holds every story
this run placed in the edition and (2) the public edition page shows them.

Token: SV_INGEST_TOKEN in the environment, or a line SV_INGEST_TOKEN=... in
~/.config/keeping-up-sv/ingest.env. Base URL: SV_BASE_URL (optional).
Safe to rerun: the server upserts by canonical URL and keeps one row per
story per edition.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import SSL_CONTEXT, UA  # noqa: E402

CONFIG = Path.home() / ".config" / "keeping-up-sv" / "ingest.env"
BATCH = 40


def setting(name: str, default: str | None = None) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    if CONFIG.exists():
        for line in CONFIG.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return default


def call(method: str, url: str, token: str | None = None, body: dict | None = None, timeout: float = 60) -> tuple[int, dict | str]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as r:
                raw = r.read().decode()
                status = r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read().decode(errors="replace"), e.code
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == 2:
                return 0, f"{type(e).__name__}: {e}"
            time.sleep(3 + attempt * 5)
            continue
        if status in (502, 503, 504) and attempt < 2:
            time.sleep(3 + attempt * 5)
            continue
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, raw
    return 0, "unreachable"


REQUIRED = ("url", "title", "source", "source_name", "category", "score")


def load_curated(path: Path) -> list[dict]:
    doc = json.loads(path.read_text())
    items = doc["items"] if isinstance(doc, dict) else doc
    problems = [f"item {i}: missing {k}" for i, it in enumerate(items) for k in REQUIRED if it.get(k) in (None, "")]
    if problems:
        sys.exit("curated file is incomplete:\n  " + "\n  ".join(problems[:20]))
    allowed = {"url", "title", "source", "source_name", "category", "tags", "excerpt", "summary", "author",
               "published_at", "claim_status", "funding", "embed_url", "mentions", "score", "score_detail"}
    return [{k: v for k, v in it.items() if k in allowed and v is not None} for it in items]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date")
    ap.add_argument("--curated", type=Path)
    ap.add_argument("--sources", type=Path, help="sources.json written by collect.py")
    ap.add_argument("--notes", default=None)
    ap.add_argument("--check", action="store_true", help="verify token and connectivity, write nothing")
    args = ap.parse_args()

    base = (setting("SV_BASE_URL", "https://induscore.site/sv") or "").rstrip("/")
    token = setting("SV_INGEST_TOKEN")
    if not token:
        sys.exit(f"No ingest token. Set SV_INGEST_TOKEN or put SV_INGEST_TOKEN=... in {CONFIG} (see the skill's SKILL.md, 'One-time setup').")

    if args.check:
        status, health = call("GET", f"{base}/api/health")
        print(f"site health: HTTP {status} {health}")
        status, res = call("GET", f"{base}/api/ingest/editions/2026-01-01", token)
        print(f"ingest token: {'ok' if status == 200 else f'REFUSED (HTTP {status}: {res})'}")
        sys.exit(0 if status == 200 else 1)

    if not (args.date and args.curated and args.sources):
        ap.error("--date, --curated and --sources are required")
    items = load_curated(args.curated)
    statuses = json.loads(args.sources.read_text())
    run_dir = args.curated.parent

    status, res = call("POST", f"{base}/api/ingest/runs", token, {"feed_date": args.date, "notes": args.notes})
    if status != 200:
        sys.exit(f"could not start a run: HTTP {status} {res}")
    run_id = res["run_id"]
    (run_dir / "run.json").write_text(json.dumps({"run_id": run_id, "date": args.date}))
    print(f"run {run_id} started for {args.date} as {res['operator']}")

    totals = {"inserted": 0, "updated": 0, "merged": 0, "rejected": 0}
    results: list[dict] = []
    errors: list[str] = []
    for i in range(0, len(items), BATCH):
        chunk = items[i : i + BATCH]
        status, res = call("POST", f"{base}/api/ingest/runs/{run_id}/items", token, {"items": chunk})
        if status != 200:
            errors.append(f"batch {i // BATCH + 1}: HTTP {status} {str(res)[:300]}")
            continue
        for k in totals:
            totals[k] += res[k]
        for r in res["results"]:
            r["index"] += i
            results.append(r)
    for r in results:
        if r["outcome"] == "rejected":
            errors.append(f"rejected item {r['index']} ({items[r['index']]['url']}): {r['reason']}")

    kept_by_source: dict[str, int] = {}
    for it in items:
        kept_by_source[it["source"]] = kept_by_source.get(it["source"], 0) + 1
    src_report = [{"source": s["source"], "name": s.get("name"), "ok": s["ok"], "fetched": s["fetched"], "kept": kept_by_source.get(s["source"], 0),
                   "error": s["error"]} for s in statuses]
    persisted = totals["inserted"] + totals["updated"] + totals["merged"]
    if persisted == 0:
        final = "failed"
    elif any(not s["ok"] for s in statuses) or totals["rejected"] or errors:
        final = "partial"
    else:
        final = "complete"
    status, fin = call("POST", f"{base}/api/ingest/runs/{run_id}/finish", token,
                       {"status": final, "sources": src_report, "errors": [e[:500] for e in errors][:100], "notes": args.notes})
    if status != 200:
        sys.exit(f"could not finish run {run_id}: HTTP {status} {fin}")

    # ---- verify 1: the database has every story this run put in the edition
    status, ed = call("GET", f"{base}/api/ingest/editions/{args.date}", token)
    in_edition = {r["item_id"] for r in ed.get("items", [])} if status == 200 else set()
    expected = {r["id"] for r in results if r["outcome"] != "rejected" and r.get("edition") == args.date}
    missing_db = sorted(expected - in_edition)

    # ---- verify 2: the public page shows the top stories (cache is cleared on ingest; allow a minute)
    top = [r for r in ed.get("items", [])][:5] if status == 200 else []
    page_ok, missing_page = False, [t["title"] for t in top]
    for _ in range(6):
        st, page = call("GET", f"{base}/{args.date}?v={int(time.time())}")
        if st == 200 and isinstance(page, str):
            text = html.unescape(page)
            missing_page = [t["title"] for t in top if t["title"] not in text]
            if not missing_page:
                page_ok = True
                break
        time.sleep(10)

    report = {
        "run_id": run_id, "date": args.date, "status": fin["status"], "sent": len(items), **totals,
        "edition_items": fin["edition_items"], "already_in_other_editions": [r for r in results if r.get("note")],
        "sources_ok": [s["source"] for s in statuses if s["ok"]],
        "sources_failed": [{"source": s["source"], "error": s["error"]} for s in statuses if not s["ok"]],
        "errors": errors, "db_verified": not missing_db and status == 200, "missing_in_db": missing_db,
        "page_verified": page_ok, "missing_on_page": missing_page, "page": f"{base}/{args.date}",
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != "already_in_other_editions"}, indent=1, ensure_ascii=False))
    if report["already_in_other_editions"]:
        print(f"{len(report['already_in_other_editions'])} stories were already featured in an earlier edition and were not repeated.")
    sys.exit(0 if report["db_verified"] and page_ok and final != "failed" else 2)


if __name__ == "__main__":
    main()
