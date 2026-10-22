"""Shared rules for Keeping Up with Silicon Valley: canonical URLs, stable
item IDs, near-duplicate keys and embed detection.

Standard library only. The aggregation skill ships this file to both
founders' laptops through teamctx, and the VM API imports the same file, so
the client and the server can never disagree about what counts as a duplicate.
"""
from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from zoneinfo import ZoneInfo

    PRODUCT_TZ = ZoneInfo("America/Los_Angeles")
except Exception:  # Windows without tzdata: PT is UTC-7 for most of the year
    PRODUCT_TZ = timezone(timedelta(hours=-7), "PT")

MAX_URL = 2048

# Query parameters that only track the click. Everything else is kept, sorted,
# because some sites (news.ycombinator.com/item?id=...) need their query.
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid",
    "ref", "ref_src", "ref_url", "referrer", "_hsenc", "_hsmi", "mkt_tok",
    "guccounter", "guce_referrer", "guce_referrer_sig", "ncid", "cmpid", "sr_share",
    "share", "via", "trk", "trkCampaign", "smid",
}
TRACKING_PREFIXES = ("utm_", "pk_", "hsa_", "vero_", "oly_")

HOST_ALIASES = {
    "twitter.com": "x.com", "mobile.twitter.com": "x.com", "www.twitter.com": "x.com",
    "mobile.x.com": "x.com", "www.x.com": "x.com",
    "old.reddit.com": "www.reddit.com", "np.reddit.com": "www.reddit.com",
    "reddit.com": "www.reddit.com", "m.reddit.com": "www.reddit.com",
    "m.youtube.com": "www.youtube.com", "youtube.com": "www.youtube.com",
}

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by",
    "from", "as", "is", "are", "its", "it", "this", "that", "be", "new", "how", "why",
    "what", "show", "hn", "launch", "ask", "tell", "yc",
}


def canonical_url(raw: str) -> str:
    """The URL we store and link to: tracking parameters and fragments removed,
    known host aliases folded. Raises ValueError for anything that is not a
    plain public http(s) URL."""
    if not isinstance(raw, str):
        raise ValueError("url must be a string")
    raw = raw.strip()
    if not raw or len(raw) > MAX_URL or any(c.isspace() for c in raw):
        raise ValueError("url is empty, too long or contains whitespace")
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError("url must be http or https")
    if parts.username or parts.password:
        raise ValueError("url must not carry credentials")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or "." not in host or host.endswith((".local", ".internal", ".localhost")) or host == "localhost":
        raise ValueError("url host is not public")
    if re.fullmatch(r"[\d.]+", host) or ":" in host:
        raise ValueError("url host must be a domain name")
    host = HOST_ALIASES.get(host, host)
    path = parts.path or "/"

    if host == "youtu.be":
        vid = path.strip("/").split("/")[0]
        host, path, query = "www.youtube.com", "/watch", [("v", vid)]
    else:
        query = [
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
            if k not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)
        ]
        if host == "www.youtube.com" and path == "/watch":
            query = [(k, v) for k, v in query if k == "v"]
        elif host == "x.com":
            query = []  # only share tracking (s=, t=) ever rides on a status URL
    if len(path) > 1:
        path = path.rstrip("/")
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    return urlunsplit((scheme, host + port, path, urlencode(sorted(query)), ""))


def url_key(url: str) -> str:
    """Identity of a URL regardless of scheme and a leading www."""
    parts = urlsplit(canonical_url(url))
    host = parts.netloc[4:] if parts.netloc.startswith("www.") else parts.netloc
    return f"{host}{parts.path}{'?' + parts.query if parts.query else ''}"


def item_id(url: str) -> str:
    digest = hashlib.sha256(url_key(url).encode()).digest()
    return base64.b32encode(digest).decode().lower()[:12]


def title_tokens(title: str) -> list[str]:
    text = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[’'`]s\b", "", text)
    words = re.findall(r"[a-z0-9$]+(?:\.[0-9]+)?", text)
    return [w for w in words if w not in STOPWORDS]


def dedupe_key(title: str) -> str:
    return " ".join(title_tokens(title)[:10])


def similar_titles(a: str, b: str, threshold: float = 0.75) -> bool:
    """Near-identical headlines (syndicated copies, one word changed). Needs at
    least five meaningful words each, so short generic titles never merge."""
    ta, tb = set(title_tokens(a)), set(title_tokens(b))
    if len(ta) < 5 or len(tb) < 5:
        return dedupe_key(a) == dedupe_key(b) and bool(ta)
    return len(ta & tb) / len(ta | tb) >= threshold


_X_STATUS = re.compile(r"^/[A-Za-z0-9_]{1,15}/status(?:es)?/(\d{5,25})")
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def detect_embed(url: str) -> tuple[str, str] | None:
    """('x', status id) or ('youtube', video id) when the platform offers an
    official embed for this URL; None otherwise."""
    try:
        parts = urlsplit(canonical_url(url))
    except ValueError:
        return None
    if parts.netloc == "x.com":
        m = _X_STATUS.match(parts.path)
        return ("x", m.group(1)) if m else None
    if parts.netloc == "www.youtube.com":
        if parts.path == "/watch":
            vid = dict(parse_qsl(parts.query)).get("v", "")
        elif parts.path.startswith(("/shorts/", "/embed/", "/live/")):
            vid = parts.path.split("/")[2]
        else:
            return None
        return ("youtube", vid) if _YT_ID.match(vid) else None
    return None


def edition_window(day: date, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Stories considered for edition `day`: the 48 hours ending at the end of
    that day in Pacific time, never past `now`. Windows overlap on purpose so a
    late-evening story is not missed; the database keeps each story in one
    edition only."""
    end = datetime.combine(day + timedelta(days=1), time(0), PRODUCT_TZ)
    start = end - timedelta(hours=48)
    now = now or datetime.now(timezone.utc)
    return start, min(end, now)


def today_pt(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(PRODUCT_TZ).date()
