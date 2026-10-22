#!/usr/bin/env python3
"""Collect candidate stories for one edition of Keeping Up with Silicon Valley.

  python3 collect.py [--date YYYY-MM-DD] [--out DIR] [--only id,id]

Reads every source in ../sources.json, keeps what was published inside the
edition window (svlib.edition_window), normalizes URLs, merges duplicates
across sources, pre-scores, and writes:

  DIR/candidates.json   ranked candidates for Claude Code to curate
  DIR/sources.json      per-source status: ok, fetched, in window, error

A failing source is recorded and skipped; the run carries on. Standard
library only, so it runs on any laptop with Python 3.10+.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import svlib  # noqa: E402

UA = "Mozilla/5.0 (compatible; KeepingUpSV/1.0; +https://induscore.site/sv/about)"
SKILL_DIR = Path(__file__).resolve().parents[1]
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
}

# ---------------------------------------------------------------- fetching


class SourceError(Exception):
    pass


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS everywhere. python.org's macOS Python ships with an empty
    CA store, so fall back to certifi or the operating system's bundle."""
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) == 0:
        try:
            import certifi  # type: ignore

            ctx.load_verify_locations(certifi.where())
        except ImportError:
            for bundle in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
                if os.path.exists(bundle):
                    ctx.load_verify_locations(bundle)
                    break
    return ctx


SSL_CONTEXT = _ssl_context()


def fetch(url: str, *, timeout: float = 20, tries: int = 3, max_bytes: int = 8_000_000) -> bytes:
    """GET with a short retry on 429/5xx/timeouts, honouring Retry-After up to 20s."""
    last = ""
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
                return resp.read(max_bytes)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                break
            wait = e.headers.get("Retry-After", "")
            time.sleep(min(int(wait), 20) if wait.isdigit() else 2 + attempt * 3)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = f"{type(e).__name__}: {getattr(e, 'reason', e)}"
            if attempt == tries - 1:
                break
            time.sleep(2 + attempt * 3)
    raise SourceError(f"{last} for {urllib.parse.urlsplit(url).netloc}")


# ---------------------------------------------------------------- text helpers


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "figure", "figcaption"):
            self.skip += 1
        elif tag in ("p", "br", "li", "div"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "figure", "figcaption") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    p = _Text()
    try:
        p.feed(s)
        text = "".join(p.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", s)
    return " ".join(html.unescape(text).split())


BOILERPLATE = re.compile(
    r"(The post .{3,200} appeared first on .{2,80}\.?$|Continue reading.*$|Read more.*$|\[…\]|\[\.\.\.\]|"
    r"Discussion \| Link$|submitted by .*$)", re.I)


def excerpt_of(text: str, limit: int = 300) -> str | None:
    text = BOILERPLATE.sub("", text).strip(" -–—|")
    if len(text) < 25:
        return None
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if end > limit * 0.55:
        return cut[: end + 1]
    return cut[: cut.rfind(" ")].rstrip(",;:") + "…"


def clean_title(t: str) -> str:
    t = " ".join(html.unescape(t or "").split())
    if len(t) > 220:
        t = t[:220]
        t = t[: t.rfind(" ")].rstrip(",;:") + "…"
    return t


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def pretty_publisher(url: str) -> str:
    host = urllib.parse.urlsplit(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    known = {
        "github.com": "GitHub", "x.com": "X", "youtube.com": "YouTube", "techcrunch.com": "TechCrunch",
        "bloomberg.com": "Bloomberg", "reuters.com": "Reuters", "nytimes.com": "The New York Times",
        "wsj.com": "The Wall Street Journal", "ft.com": "Financial Times", "theinformation.com": "The Information",
        "cnbc.com": "CNBC", "axios.com": "Axios", "theverge.com": "The Verge", "arstechnica.com": "Ars Technica",
        "wired.com": "Wired", "businessinsider.com": "Business Insider", "fortune.com": "Fortune",
        "forbes.com": "Forbes", "semafor.com": "Semafor", "venturebeat.com": "VentureBeat",
        "theguardian.com": "The Guardian", "washingtonpost.com": "The Washington Post", "arxiv.org": "arXiv",
        "openai.com": "OpenAI", "anthropic.com": "Anthropic", "blog.google": "Google", "huggingface.co": "Hugging Face",
        "news.ycombinator.com": "Hacker News", "reddit.com": "Reddit", "producthunt.com": "Product Hunt",
        "ycombinator.com": "Y Combinator", "substack.com": "Substack", "medium.com": "Medium",
        "geekwire.com": "GeekWire", "siliconangle.com": "SiliconANGLE", "news.crunchbase.com": "Crunchbase News",
        "9to5mac.com": "9to5Mac", "engadget.com": "Engadget", "zdnet.com": "ZDNET", "theregister.com": "The Register",
    }
    return known.get(host, host)[:60]


# ---------------------------------------------------------------- feed parsing


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


IMG_SRC = re.compile(r'<img[^>]+src="(https://[^"]+)"', re.I)
IMAGE_EXT = re.compile(r"\.(jpe?g|png|webp|avif|gif)(\?|$)", re.I)


def feed_image(it: ET.Element, html_text: str) -> str | None:
    """The image a feed item carries: an image enclosure, media:content or
    media:thumbnail, else the first <img> in its HTML. A link, never a copy."""
    for enc in it.findall("enclosure"):
        if enc.get("type", "").startswith("image/") and enc.get("url", "").startswith("https://"):
            return enc.get("url")
    for tag in ("media:content", "media:thumbnail", "media:group/media:content"):
        for m in it.findall(tag, NS):
            url = m.get("url", "")
            if url.startswith("https://") and (m.get("medium") == "image" or m.get("type", "").startswith("image/")
                                               or IMAGE_EXT.search(url) or tag.endswith("thumbnail")):
                return url
    m = IMG_SRC.search(html_text or "")
    return html.unescape(m.group(1)) if m else None


def parse_feed(raw: bytes) -> list[dict]:
    """RSS 2.0 and Atom entries as {title, link, published, html, author, image}."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise SourceError(f"feed is not valid XML ({e})")
    out = []
    if root.tag.endswith("rss") or root.find("channel") is not None:
        for it in root.iter("item"):
            content = it.find("content:encoded", NS)
            out.append({
                "title": _text(it.find("title")),
                "link": _text(it.find("link")) or _text(it.find("guid")),
                "published": parse_date(_text(it.find("pubDate")) or _text(it.find("dc:date", NS))),
                "description": _text(it.find("description")),
                "html": _text(it.find("description")) or _text(content),
                "author": _text(it.find("dc:creator", NS)) or _text(it.find("author")),
                "image": feed_image(it, _text(it.find("description")) + _text(content)),
            })
    else:
        for it in root.iter(f"{{{NS['atom']}}}entry"):
            link = ""
            for ln in it.findall("atom:link", NS):
                if ln.get("rel", "alternate") == "alternate":
                    link = ln.get("href", "")
                    break
            out.append({
                "title": html_to_text(_text(it.find("atom:title", NS))),
                "link": link,
                "published": parse_date(_text(it.find("atom:published", NS)) or _text(it.find("atom:updated", NS))),
                "description": "",
                "html": _text(it.find("atom:summary", NS)) or _text(it.find("atom:content", NS)),
                "author": _text(it.find("atom:author/atom:name", NS)),
                "image": feed_image(it, _text(it.find("atom:content", NS)) or _text(it.find("atom:summary", NS))),
            })
    return out


# ---------------------------------------------------------------- classification

RELEVANT = re.compile(
    r"\b(start-?ups?|founders?|funding|raises?|raised|raising|series [a-f]|seed|pre-seed|valuation|venture|vcs?|"
    r"investors?|invests?|acqui(res?|red|sition|-?hires?)|ipo|merger|layoffs?|launch(es|ed)?|unveil(s|ed)?|"
    r"announc(es|ed)|releases?|open[- ]sources?|ai|a\.i\.|llms?|models?|agents?|agentic|gpus?|chips?|nvidia|"
    r"openai|anthropic|claude|gemini|deepmind|mistral|xai|grok|meta|google|microsoft|apple|amazon|tesla|spacex|"
    r"y ?combinator|yc|saas|developers?|api|sdk|robots?|robotics|humanoid|autonomous|self-driving|fintech|"
    r"stablecoin|crypto|data ?cent(er|re)s?|semiconductor|tsmc|quantum|cybersecurity|breach|antitrust|"
    r"show hn|launch hn|ask hn)\b", re.I)

CATEGORY_RULES = [
    ("acquisition", re.compile(r"\b(acquires?|acquired|acquisition|acqui-?hires?|to buy|buys|agrees to buy|merger|merges|takeover)\b", re.I)),
    ("funding", re.compile(
        r"\b(raises?|raised|raising|funding round|series [a-f]\b|seed round|pre-seed|seed funding|valuation|"
        r"secures? \$|closes? \$|new fund|lands? \$|bags? \$|\$\d+(\.\d+)?\s?(m|b|bn|million|billion)\b.*\b(round|funding|investment))", re.I)),
    ("launch", re.compile(r"\b(launch(es|ed|ing)?|introduc(es|ing|ed)|unveil(s|ed)?|now available|general availability|"
                          r"show hn|launch hn|ships?|debuts?|rolls? out|open[- ]sources?)\b", re.I)),
]

TAG_RULES = [
    ("ai", r"\b(ai|a\.i\.|artificial intelligence|llms?|gpt-?\d*|models?|machine learning|openai|anthropic|claude|gemini|deepmind|mistral|genai)\b"),
    ("ai-agents", r"\b(agents?|agentic|copilots?|assistant)\b"),
    ("devtools", r"\b(developers?|devtools?|api|sdk|ide|github|coding|code|compiler|programming|open[- ]source|rust|python|typescript)\b"),
    ("infra", r"\b(cloud|infrastructure|database|kubernetes|data ?cent(er|re)s?|inference|serverless|storage|networking)\b"),
    ("chips", r"\b(chips?|semiconductors?|nvidia|tsmc|gpus?|asics?|amd|intel)\b"),
    ("robotics", r"\b(robots?|robotics|humanoids?|drones?|autonomous|self-driving|waymo)\b"),
    ("fintech", r"\b(fintech|payments?|banking|banks?|stripe|lending|insurance|neobank)\b"),
    ("crypto", r"\b(crypto|bitcoin|ethereum|stablecoins?|blockchain|web3)\b"),
    ("security", r"\b(security|cybersecurity|breach|vulnerabilit(y|ies)|hack(ed|ers?)?|ransomware|exploit)\b"),
    ("climate", r"\b(climate|energy|batter(y|ies)|solar|nuclear|fusion|carbon|ev|electric vehicles?)\b"),
    ("health", r"\b(health|healthcare|biotech|medical|drug|clinical|therapeutics?)\b"),
    ("defense", r"\b(defense|defence|military|pentagon|national security)\b"),
    ("consumer", r"\b(consumer|social|app store|iphone|creator|shopping|dating)\b"),
    ("enterprise", r"\b(enterprise|saas|b2b|crm|erp|workflow|productivity)\b"),
    ("open-source", r"\b(open[- ]source|open[- ]weights?)\b"),
    ("vc", r"\b(venture|vcs?|investors?|new fund|limited partners|lps?)\b"),
    ("ipo", r"\b(ipo|goes public|public listing|s-1)\b"),
]
TAG_RES = [(t, re.compile(p, re.I)) for t, p in TAG_RULES]

AMOUNT = re.compile(r"(?<![\w$])(?:US)?\$\s?(\d{1,4}(?:[.,]\d{1,3})?)\s?(million|billion|bn|m|b|k)\b", re.I)
ROUND = re.compile(r"\b(pre-seed|seed|series [a-h](?:[- ]?\d|\+)?|growth round|bridge round)\b", re.I)


def guess_category(text: str, default: str) -> str:
    for cat, rx in CATEGORY_RULES:
        if rx.search(text):
            return cat
    return default


def guess_tags(text: str, base: list[str]) -> list[str]:
    tags = list(base)
    for tag, rx in TAG_RES:
        if rx.search(text) and tag not in tags:
            tags.append(tag)
    return tags[:6]


def funding_hint(text: str) -> dict | None:
    amount = AMOUNT.search(text)
    rnd = ROUND.search(text)
    if not amount and not rnd:
        return None
    hint = {}
    if amount:
        unit = amount.group(2).lower()
        unit = {"million": "M", "m": "M", "billion": "B", "bn": "B", "b": "B", "k": "K"}[unit]
        hint["amount"] = f"${amount.group(1)}{unit}"
    if rnd:
        hint["round"] = rnd.group(1).title().replace("Pre-Seed", "Pre-seed")
    return hint


# ---------------------------------------------------------------- per-source collectors


def candidate(src: dict, *, url: str, title: str, published: datetime | None, text: str = "", author: str = "",
              source_name: str | None = None, mentions: list[dict] | None = None, engagement: dict | None = None,
              tags: list[str] | None = None, category: str | None = None, extra: dict | None = None,
              image_url: str | None = None, image_kind: str = "cover") -> dict | None:
    try:
        url = svlib.canonical_url(url)
    except ValueError:
        return None
    title = clean_title(title)
    if len(title) < 3:
        return None
    blob = f"{title} {text}"
    cat = category or guess_category(blob, src["category"])
    return {
        "id": svlib.item_id(url),
        "url": url,
        "title": title,
        "source": src["id"],
        "source_name": (source_name or src["name"])[:60],
        "published_at": published.isoformat() if published else None,
        "excerpt": excerpt_of(text),
        "author": (author or "")[:120] or None,
        "category": cat,
        "tags": guess_tags(blob, (tags or []) + src.get("tags", [])),
        "claim_status": src["claim"],
        "funding_hint": funding_hint(blob) if cat == "funding" else None,
        "mentions": mentions or [],
        "engagement": engagement or {},
        "found_in": [src["id"]],
        "image_url": image_url if image_url and image_url.startswith("https://") else None,
        "image_kind": image_kind if image_url else None,
        "weight": src["weight"],
        "relevant": bool(RELEVANT.search(blob)),
        **({"extra": extra} if extra else {}),
    }


def collect_rss(src: dict, start: datetime, end: datetime) -> tuple[list[dict], int]:
    out, fetched = [], 0
    for feed_url in src.get("urls") or [src["url"]]:
        for e in parse_feed(fetch(feed_url)):
            fetched += 1
            if not e["published"] or not (start <= e["published"] <= end):
                continue
            url, source_name, mentions = e["link"], None, []
            if src.get("original_in_description"):
                # Techmeme: the item links to Techmeme's page; the original article is the first outside link.
                hrefs = re.findall(r'href="(https?://[^"]+)"', e["description"] or e["html"], re.I)
                original = next((h for h in hrefs if "techmeme.com" not in h), None)
                if original:
                    try:
                        mentions = [{"url": svlib.canonical_url(e["link"]), "source": src["id"], "label": src["name"]}]
                    except ValueError:
                        mentions = []
                    url, source_name = html.unescape(original), pretty_publisher(original)
            text = html_to_text(e["html"])
            if src.get("original_in_description"):
                text = re.sub(r"^.{0,80}?:\s", "", text)  # drop "Bloomberg:" style lead-in
            c = candidate(src, url=url, title=html_to_text(e["title"]), published=e["published"], text=text,
                          author=e["author"], source_name=source_name, mentions=mentions,
                          image_url=None if src.get("original_in_description") else e.get("image"))
            if c:
                out.append(c)
    return out, fetched


HN_API = "https://hn.algolia.com/api/v1/"


def collect_hn(src: dict, start: datetime, end: datetime, is_today: bool) -> tuple[list[dict], int]:
    s, e = int(start.timestamp()), int(end.timestamp())
    window = f"created_at_i>{s},created_at_i<{e}"
    queries = [
        f"search?tags=story&numericFilters={window},points>=100&hitsPerPage=100",
        f"search?tags=show_hn&numericFilters={window},points>=20&hitsPerPage=50",
        f"search?tags=ask_hn&numericFilters={window},points>=60&hitsPerPage=30",
        f"search?query=%22Launch%20HN%22&tags=story&numericFilters={window}&hitsPerPage=30",
    ]
    if is_today:
        queries.insert(0, "search?tags=front_page&hitsPerPage=60")
    hits: dict[str, dict] = {}
    for q in queries:
        for h in json.loads(fetch(HN_API + q)).get("hits", []):
            hits.setdefault(h["objectID"], h)
    out = []
    for h in hits.values():
        published = parse_date(h.get("created_at"))
        if not published or not (start <= published <= end) or not h.get("title"):
            continue
        thread = f"https://news.ycombinator.com/item?id={h['objectID']}"
        points, comments = h.get("points") or 0, h.get("num_comments") or 0
        mention = {"url": thread, "source": "hackernews", "label": "Hacker News", "points": points, "comments": comments}
        title = h["title"]
        is_text = not h.get("url")
        tags = []
        category = None
        if re.match(r"(ask|tell) hn", title, re.I):
            category = "discussion"
        elif re.match(r"(show|launch) hn", title, re.I):
            category = "launch"
        if re.match(r"launch hn", title, re.I):
            tags.append("yc")
        c = candidate(
            src, url=thread if is_text else h["url"], title=title, published=published,
            # h["author"] is whoever submitted it to HN, not the author of the linked work.
            text=html_to_text(h.get("story_text") or ""),
            source_name="Hacker News" if is_text else pretty_publisher(h["url"]),
            mentions=[] if is_text else [mention], engagement={"points": points, "comments": comments},
            tags=tags, category=category,
        )
        if c:
            if is_text:
                c["engagement_self"] = {"points": points, "comments": comments}
            out.append(c)
    return out, len(hits)


def collect_yc(src: dict, start: datetime, end: datetime) -> tuple[list[dict], int]:
    out, fetched = [], 0
    for page in range(0, 6):
        data = json.loads(fetch(f"{src['url']}?page={page}"))
        hits = data.get("hits", [])
        fetched += len(hits)
        oldest = None
        for h in hits:
            published = parse_date(h.get("created_at"))
            oldest = published if oldest is None or (published and published < oldest) else oldest
            if not published or not (start <= published <= end):
                continue
            company = h.get("company") or {}
            yc_tags = [t.lower().replace(" ", "-") for t in company.get("tags", [])]
            tags = [t for t in ("ai" if "ai" in yc_tags or "artificial-intelligence" in yc_tags else None,) if t]
            text = h.get("tagline") or ""
            c = candidate(
                src, url=h.get("search_path") or f"https://www.ycombinator.com/launches/{h['slug']}",
                title=h.get("title", ""), published=published, text=text, category="launch",
                engagement={"votes": h.get("total_vote_count") or 0}, tags=tags,
                extra={"company": company.get("name"), "batch": company.get("batch"), "company_url": company.get("url"),
                       "industry": company.get("industry")},
                image_url=company.get("logo"), image_kind="logo",
            )
            if c:
                c["excerpt"] = (text or None) and text[:300]
                out.append(c)
        if not hits or (oldest and oldest < start) or page + 1 >= data.get("nbPages", 1):
            break
    return out, fetched


def collect_reddit(src: dict, start: datetime, end: datetime) -> tuple[list[dict], int]:
    entries = parse_feed(fetch(src["url"], tries=2))
    out = []
    for e in entries:
        if not e["published"] or not (start <= e["published"] <= end):
            continue
        text = html_to_text(e["html"])
        sub = re.search(r"/r/([A-Za-z0-9_]+)/", e["link"] or "")
        c = candidate(src, url=e["link"], title=e["title"], published=e["published"], text=text,
                      source_name=f"r/{sub.group(1)}" if sub else "Reddit", category="discussion")
        if c:
            out.append(c)
    return out, len(entries)


# ---------------------------------------------------------------- scoring + merging


def prescore(c: dict, end: datetime) -> dict:
    hours = 24.0
    if c["published_at"]:
        hours = max(0.0, (end - datetime.fromisoformat(c["published_at"])).total_seconds() / 3600)
    recency = 30 * math.exp(-hours / 30)
    eng = c.get("engagement") or {}
    if "points" in eng:
        engagement = 35 * min(1.0, math.log10(1 + eng["points"] + 0.5 * eng.get("comments", 0)) / math.log10(1 + 900))
    elif "votes" in eng:
        engagement = 35 * min(1.0, math.log10(1 + eng["votes"]) / math.log10(1 + 120))
    else:
        engagement = 12.0  # an editor (the publication) already chose it
    kind = {"funding": 10, "acquisition": 10, "launch": 6, "analysis": 2}.get(c["category"], 0)
    multi = min(10, 5 * (len(c["found_in"]) - 1))
    off_topic = 0 if c["relevant"] else -25
    total = max(0.0, min(100.0, recency + engagement + c["weight"] + kind + multi + off_topic))
    c["score"] = round(total, 1)
    c["score_detail"] = {
        "recency": round(recency, 1), "engagement": round(engagement, 1), "source": c["weight"], "kind": kind,
        "multi_source": multi, "off_topic": off_topic, "hours_old": round(hours, 1),
    }
    return c


def merge(cands: list[dict]) -> list[dict]:
    """One candidate per story. The higher-weight source stays primary; the
    other sighting becomes a mention and keeps its engagement."""
    cands.sort(key=lambda c: -c["weight"])
    kept: list[dict] = []
    by_id: dict[str, dict] = {}
    for c in cands:
        twin = by_id.get(c["id"]) or next((k for k in kept if svlib.similar_titles(k["title"], c["title"])), None)
        if not twin:
            kept.append(c)
            by_id[c["id"]] = c
            continue
        if c["source"] not in twin["found_in"]:
            twin["found_in"].append(c["source"])
        seen = {m["url"] for m in twin["mentions"]} | {twin["url"]}
        for m in c["mentions"] + ([] if c["url"] in seen else [{"url": c["url"], "source": c["source"], "label": c["source_name"]}]):
            if m["url"] not in seen:
                twin["mentions"].append(m)
                seen.add(m["url"])
        for k, v in (c.get("engagement") or {}).items():
            twin.setdefault("engagement", {}).setdefault(k, v)
        if not twin.get("image_url") and c.get("image_url"):
            twin["image_url"], twin["image_kind"] = c["image_url"], c.get("image_kind")
        for t in c["tags"]:
            if t not in twin["tags"] and len(twin["tags"]) < 6:
                twin["tags"].append(t)
        if twin["category"] in ("news", "discussion") and c["category"] in ("funding", "acquisition", "launch"):
            twin["category"] = c["category"]
            twin["funding_hint"] = twin.get("funding_hint") or c.get("funding_hint")
        twin["relevant"] = twin["relevant"] or c["relevant"]
    return kept


# ---------------------------------------------------------------- main


def run_source(src: dict, start: datetime, end: datetime, is_today: bool) -> tuple[dict, list[dict]]:
    t0 = time.time()
    try:
        if src["kind"] == "rss":
            cands, fetched = collect_rss(src, start, end)
        elif src["kind"] == "hn":
            cands, fetched = collect_hn(src, start, end, is_today)
        elif src["kind"] == "yc":
            cands, fetched = collect_yc(src, start, end)
        elif src["kind"] == "reddit":
            cands, fetched = collect_reddit(src, start, end)
        else:
            raise SourceError(f"unknown kind {src['kind']}")
        if src.get("filter"):
            cands = [c for c in cands if c["relevant"]]
        return {"source": src["id"], "name": src["name"], "ok": True, "fetched": fetched, "in_window": len(cands),
                "seconds": round(time.time() - t0, 1), "error": None}, cands
    except Exception as e:  # one bad source never stops the run
        return {"source": src["id"], "name": src["name"], "ok": False, "fetched": 0, "in_window": 0,
                "seconds": round(time.time() - t0, 1), "error": str(e)[:280] or type(e).__name__}, []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="edition date YYYY-MM-DD (default: today in Pacific time)")
    ap.add_argument("--out", help="output directory (default: <tmp>/keeping-up-sv/<date>)")
    ap.add_argument("--only", help="comma-separated source ids to run")
    args = ap.parse_args()

    today = svlib.today_pt()
    day = date.fromisoformat(args.date) if args.date else today
    if day > today:
        sys.exit(f"{day} is in the future (today in Pacific time is {today})")
    start, end = svlib.edition_window(day)
    out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "keeping-up-sv" / day.isoformat()
    out.mkdir(parents=True, exist_ok=True)

    sources = [s for s in json.loads((SKILL_DIR / "sources.json").read_text())["sources"] if s.get("enabled", True)]
    if args.only:
        wanted = set(args.only.split(","))
        sources = [s for s in sources if s["id"] in wanted]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda s: run_source(s, start, end, day == today), sources))

    statuses = [r[0] for r in results]
    cands = merge([c for _, cs in results for c in cs])
    cands = sorted((prescore(c, end) for c in cands), key=lambda c: -c["score"])
    (out / "candidates.json").write_text(json.dumps(
        {"date": day.isoformat(), "window": [start.isoformat(), end.isoformat()], "generated_at": datetime.now(timezone.utc).isoformat(),
         "candidates": cands}, indent=1, ensure_ascii=False))
    (out / "sources.json").write_text(json.dumps(statuses, indent=1))

    ok = sum(s["ok"] for s in statuses)
    print(f"edition {day}  window {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC")
    print(f"sources ok {ok}/{len(statuses)}; candidates {len(cands)} (after merging duplicates)")
    for s in statuses:
        print(f"  {'ok ' if s['ok'] else 'ERR'} {s['source']:<18} fetched {s['fetched']:>4}  in window {s['in_window']:>3}  {s['error'] or ''}")
    print(f"wrote {out / 'candidates.json'}")


if __name__ == "__main__":
    main()
