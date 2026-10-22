"""Optional discovery on 小红书 (Xiaohongshu) and X, through the founder's own
logged-in browser. Used by collect.py for sources of kind "login".

Neither platform has a public feed. Search needs a logged-in session, and the
only session this step ever uses is the founder's own Chrome, through
agent-reach's OpenCLI bridge (`opencli <site> search ... -f json`). It never
logs in, never reads or stores cookies, never touches a paywall. It runs:

  - when `agent-reach doctor --json` reports the channel usable through OpenCLI
    (status "ok"); or
  - when the founder passes --login-sources to collect.py and doctor lists
    OpenCLI for the channel (doctor does not probe logins itself, so it says
    "warn"): one read-only search then proves the login, and an empty answer
    or an error means the source is skipped.

Otherwise the source is recorded on the edition as
"skipped: needs login (run agent-reach configure)", which does not make the
run partial. Searches run one at a time, a few seconds apart.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import collect  # collect.py aliases itself as "collect" when run as a script
import svlib

NEEDS_LOGIN = "skipped: needs login (run agent-reach configure)"
PAUSE = 3.0           # seconds between searches (agent-reach: 2-3 s, or the platform asks for a captcha)
TIMEOUT = 90          # seconds per search
PLATFORMS = {
    # platform -> (doctor channel, opencli site, source name on items, login page to name in messages)
    "xiaohongshu": ("xiaohongshu", "xiaohongshu", "小红书", "xiaohongshu.com"),
    "twitter": ("twitter", "twitter", "X", "x.com"),
}


class Skipped(collect.SourceError):
    """The source did not run on purpose (no login): shown on the edition, not a failure."""


def _bin(name: str, env: str) -> str | None:
    if os.environ.get(env):
        return os.environ[env]
    found = shutil.which(name)
    if found:
        return found
    local = Path.home() / ".local" / "bin" / name
    return str(local) if local.exists() else None


def run_cmd(args: list[str], timeout: float) -> tuple[int, str, str]:
    """One command, no shell; (exit code, stdout, stderr). Patched in tests."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout:.0f}s"
    except OSError as e:
        return 127, "", str(e)


@lru_cache(maxsize=1)
def doctor() -> dict | None:
    """agent-reach's own health report, once per run; None when agent-reach is missing."""
    exe = _bin("agent-reach", "AGENT_REACH_BIN")
    if not exe:
        return None
    code, out, err = run_cmd([exe, "doctor", "--json"], 60)
    try:
        report = json.loads(out)
    except ValueError:
        return {"_error": (err or out or f"exit {code}").strip()[:120]}
    return report if isinstance(report, dict) else {"_error": "unexpected doctor output"}


def decide(report: dict | None, platform: str, allow_probe: bool) -> tuple[str, str]:
    """("run" | "probe" | "skip", reason). Pure, so the gate is easy to test."""
    channel, _, _, site = PLATFORMS[platform]
    if report is None:
        return "skip", "skipped: agent-reach is not installed (see the agent-reach skill); this source needs it and your login"
    if "_error" in report:
        return "skip", f"{NEEDS_LOGIN}; agent-reach doctor failed: {report['_error']}"
    ch = report.get(channel) or {}
    backend = str(ch.get("active_backend") or "")
    opencli_listed = any("opencli" in str(b).lower() for b in ch.get("backends") or [])
    if ch.get("status") == "ok" and "opencli" in backend.lower():
        return "run", f"agent-reach doctor: ok via {backend}"
    if ch.get("status") == "ok" and backend:
        return "skip", f"{NEEDS_LOGIN}; doctor's active backend is {backend}, and this step reads only through the OpenCLI bridge"
    if allow_probe and opencli_listed and ch.get("status") != "off":
        return "probe", "--login-sources: one read-only search checks your login first"
    hint = (f"; doctor: {ch.get('status', 'unknown')}, login not verified. Log in to {site} in your own Chrome, then rerun "
            "collect.py with --login-sources") if opencli_listed else ""
    return "skip", NEEDS_LOGIN + hint


# ---------------------------------------------------------------- parsing what OpenCLI returns


def rows(stdout: str) -> list[dict]:
    """OpenCLI's -f json output: a list of rows, or an object holding one."""
    try:
        data = json.loads(stdout)
    except ValueError:
        raise collect.SourceError("OpenCLI did not return JSON")
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


_COUNT = re.compile(r"^([\d.,]+)\s*([kKmMwW万亿]?)\+?$")


def count(v: object) -> int | None:
    """'1.2万' -> 12000, '3.4w' -> 34000, '1.5K' -> 1500, '2M' -> 2000000, '1,234' -> 1234."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = _COUNT.match(str(v or "").strip())
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(n * {"": 1, "k": 1e3, "m": 1e6, "w": 1e4, "万": 1e4, "亿": 1e8}[m.group(2).lower()])


_REL = re.compile(r"^(\d+)\s*(秒|分钟|小时|天|周|s|m|min|h|d|w)\s*(前|ago)?$", re.I)
_UNIT = {"秒": "seconds", "s": "seconds", "分钟": "minutes", "m": "minutes", "min": "minutes", "小时": "hours", "h": "hours",
         "天": "days", "d": "days", "周": "weeks", "w": "weeks"}
BEIJING = timezone(timedelta(hours=8))


def when(v: object, now: datetime) -> datetime | None:
    """A post's time as the platform shows it: ISO, RFC 2822, X's
    'Wed Oct 21 10:00:00 +0000 2026', 'YYYY-MM-DD', 'MM-DD', '3天前', '2h',
    '昨天 12:30', '刚刚'. Dates without a zone are read as Beijing time
    (小红书's). None when it cannot be read."""
    s = str(v or "").strip()
    if not s:
        return None
    if isinstance(v, (int, float)) or s.isdigit():
        n = float(s)
        return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, timezone.utc)
    if s in ("刚刚", "just now"):
        return now
    m = _REL.match(s)
    if m:
        return now - timedelta(**{_UNIT[m.group(2).lower()]: int(m.group(1))})
    m = re.match(r"^(今天|昨天|前天)\s*(\d{1,2}):(\d{2})$", s)
    if m:
        local = now.astimezone(BEIJING) - timedelta(days=("今天", "昨天", "前天").index(m.group(1)))
        return local.replace(hour=int(m.group(2)), minute=int(m.group(3)), second=0, microsecond=0).astimezone(timezone.utc)
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").astimezone(timezone.utc)
    except ValueError:
        pass
    m = re.match(r"^(?:(\d{4})-)?(\d{1,2})-(\d{1,2})$", s)
    if m:
        year = int(m.group(1) or now.astimezone(BEIJING).year)
        try:
            d = datetime(year, int(m.group(2)), int(m.group(3)), 12, tzinfo=BEIJING).astimezone(timezone.utc)
        except ValueError:
            return None
        return d if m.group(1) or d <= now + timedelta(days=1) else d.replace(year=year - 1)
    return collect.parse_date(s) if re.match(r"^\d{4}-\d{2}-\d{2}[T ]", s) or "," in s else None


_XHS_NOTE = re.compile(r"/(?:explore|discovery/item|search_result)/([0-9a-f]{24})")
_X_STATUS = re.compile(r"/status(?:es)?/(\d{5,25})")


def xhs_candidate(src: dict, r: dict, keyword: str, now: datetime) -> dict | None:
    """A 小红书 note. The public link is the bare note URL: the xsec_token in the
    search result belongs to the founder's session, so it stays in
    extra.open_url (candidates.json on this laptop only) and is never ingested."""
    full = str(r.get("url") or r.get("link") or "")
    m = _XHS_NOTE.search(full)
    if not m:
        return None
    published = when(r.get("published_at") or r.get("time"), now)
    likes = count(r.get("likes"))
    c = collect.candidate(src, url=f"https://www.xiaohongshu.com/explore/{m.group(1)}", title=str(r.get("title") or ""),
                          published=published, author=str(r.get("author") or ""), source_name="小红书",
                          category="discussion", engagement={"likes": likes} if likes is not None else {},
                          extra={"keyword": keyword, "open_url": full if full.startswith("https://") else None,
                                 "shown_time": str(r.get("published_at") or "")[:40]})
    return c


def x_candidate(src: dict, r: dict, keyword: str, now: datetime) -> dict | None:
    """An X post, as its status URL (the site embeds it with X's own widget)."""
    url = str(r.get("url") or "")
    m = _X_STATUS.search(url)
    status_id = m.group(1) if m else str(r.get("id") or "")
    handle = str(r.get("author") or "").lstrip("@")
    if not url and status_id.isdigit() and re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
        url = f"https://x.com/{handle}/status/{status_id}"
    if not url or not svlib.detect_embed(url):
        return None
    text = " ".join(str(r.get("text") or "").split())
    likes, views = count(r.get("likes")), count(r.get("views"))
    engagement = {k: v for k, v in (("likes", likes), ("views", views)) if v is not None}
    c = collect.candidate(src, url=url, title=text[:200], published=when(r.get("created_at"), now), text=text,
                          author=handle, source_name="X", category="discussion", engagement=engagement,
                          extra={"keyword": keyword})
    if c:
        c["embed_url"] = c["url"]
    return c


# ---------------------------------------------------------------- the collector


def search(platform: str, keyword: str, src: dict, start: datetime) -> list[dict]:
    exe = _bin("opencli", "OPENCLI_BIN")
    if not exe:
        raise Skipped(f"{NEEDS_LOGIN}; opencli is not installed")
    _, site, _, _ = PLATFORMS[platform]
    query = keyword
    if platform == "twitter" and "since:" not in query:
        query = f"{query} since:{start.date().isoformat()}"
    args = [exe, site, "search", query, "--limit", str(int(src.get("limit", 10))), *map(str, src.get("search_args", [])),
            "--window", "background", "-f", "json"]
    code, out, err = run_cmd(args, TIMEOUT)
    if code != 0:
        raise collect.SourceError(f"opencli {site} search exited {code}: {(err or out).strip()[:160]}")
    return rows(out)


def collect_login(src: dict, start: datetime, end: datetime, allow_probe: bool,
                  now: datetime | None = None, pause: float = PAUSE) -> tuple[list[dict], int]:
    platform = src["platform"]
    if platform not in PLATFORMS:
        raise collect.SourceError(f"unknown platform {platform}")
    action, reason = decide(doctor(), platform, allow_probe)
    if action == "skip":
        raise Skipped(reason)
    now = now or datetime.now(timezone.utc)
    build = xhs_candidate if platform == "xiaohongshu" else x_candidate
    out, fetched = [], 0
    for i, keyword in enumerate(src.get("keywords") or []):
        if i:
            time.sleep(pause)
        try:
            found = search(platform, keyword, src, start)
        except collect.SourceError as e:
            if action == "probe" and i == 0:
                raise Skipped(f"{NEEDS_LOGIN}; the login check failed ({str(e)[:120]})")
            raise
        if action == "probe" and i == 0 and not found:
            raise Skipped(f"{NEEDS_LOGIN}; the login check search returned nothing. Log in to {PLATFORMS[platform][3]} in your own Chrome")
        fetched += len(found)
        for r in found:
            c = build(src, r, keyword, now)
            if not c:
                continue
            published = datetime.fromisoformat(c["published_at"]) if c["published_at"] else None
            if published and not (start <= published <= end + timedelta(minutes=5)):
                continue
            out.append(c)
    return out, fetched
