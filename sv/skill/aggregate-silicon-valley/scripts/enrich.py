#!/usr/bin/env python3
"""Add pictures and embeds to a curated edition, from each story's own page.

  python3 enrich.py --curated DIR/curated.json

For every curated story it opens the original page once (if robots.txt
allows our user agent) and reads:
  - the page's preview image (og:image / twitter:image), when the story has none yet
  - YouTube videos and X posts the publisher embedded in the article body, or
    X posts it cites as a source with a link inside the article's paragraphs
It sets `image_url` (a link to the publisher's own file, never a copy) and,
when the story has no embed yet, `embed_url` (YouTube preferred, else the
first embedded X post). Everything found is listed in DIR/enrich.json and
printed with the post's author and opening words (or the video's channel and
title, from the platforms' public oEmbed endpoints), so Claude can replace or
drop an off-topic embed before ingesting. A video from the publisher's own
channel is flagged: it is often a promo for the outlet, not the story.
Standard library only; a page that fails is skipped, never fatal.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import svlib  # noqa: E402
from collect import UA, SourceError, fetch  # noqa: E402

SKIP_HOSTS = ("news.ycombinator.com", "www.reddit.com", "x.com", "www.youtube.com")
_X_STATUS = re.compile(r"https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/[A-Za-z0-9_]{1,15}/status/\d{5,25}")
_YT = re.compile(r"https?://(?:www\.)?youtube(?:-nocookie)?\.com/embed/([A-Za-z0-9_-]{11})")

_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_robots_lock = Lock()


def allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    with _robots_lock:
        if origin not in _robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.parse(fetch(origin + "/robots.txt", timeout=10, tries=1, max_bytes=500_000).decode("utf-8", "replace").splitlines())
            except SourceError as e:
                if "HTTP 401" in str(e) or "HTTP 403" in str(e):
                    rp.disallow_all = True
                else:
                    rp = None  # no robots.txt: allowed
            _robots[origin] = rp
        rp = _robots[origin]
    return rp is None or rp.can_fetch(UA, url)


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.tweets: list[str] = []      # embedded posts (blockquote.twitter-tweet)
        self.cited: list[str] = []       # posts linked from the article's own sentences
        self.videos: list[str] = []
        self._tweet_depth = 0
        self._p_depth = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src", "og:video:url", "og:video") and a.get("content"):
                self.meta.setdefault(key, a["content"].strip())
        elif tag == "blockquote" and "twitter-tweet" in a.get("class", ""):
            self._tweet_depth += 1
        elif tag == "p":
            self._p_depth += 1
        elif tag == "a" and _X_STATUS.match(a.get("href", "")):
            if self._tweet_depth:
                self.tweets.append(_X_STATUS.match(a["href"]).group(0))
            elif self._p_depth:
                self.cited.append(_X_STATUS.match(a["href"]).group(0))
        elif tag == "iframe":
            m = _YT.match(a.get("src") or a.get("data-src") or "")
            if m:
                self.videos.append(f"https://www.youtube.com/watch?v={m.group(1)}")

    def handle_endtag(self, tag):
        if tag == "blockquote" and self._tweet_depth:
            self._tweet_depth -= 1
        elif tag == "p" and self._p_depth:
            self._p_depth -= 1


def inspect(url: str) -> dict:
    host = urllib.parse.urlsplit(url).netloc
    if host in SKIP_HOSTS:
        return {"status": "skipped (platform page)"}
    if not allowed(url):
        return {"status": "skipped (robots.txt)"}
    try:
        raw = fetch(url, timeout=12, tries=1, max_bytes=2_000_000)
    except SourceError as e:
        return {"status": f"failed ({e})"}
    page = _Page()
    try:
        page.feed(raw.decode("utf-8", "replace"))
    except Exception:
        pass
    image = next((page.meta[k] for k in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src") if k in page.meta), None)
    if image:
        image = urllib.parse.urljoin(url, image)
        if not image.startswith("https://"):
            image = None
    og_video = page.meta.get("og:video:url") or page.meta.get("og:video") or ""
    videos = list(dict.fromkeys(page.videos + ([og_video] if svlib.detect_embed(og_video) else [])))
    tweets = list(dict.fromkeys(page.tweets + page.cited))
    return {"status": "ok", "image": image, "videos": videos[:3], "tweets": tweets[:5]}


def describe(embed_url: str) -> str:
    """'author | text' for an X post, 'channel | title' for a YouTube video."""
    kind = svlib.detect_embed(embed_url)
    if not kind:
        return ""
    if kind[0] == "x":
        path = urllib.parse.urlsplit(embed_url).path
        api = "https://publish.twitter.com/oembed?omit_script=1&url=" + urllib.parse.quote(f"https://twitter.com{path}", safe="")
    else:
        api = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(embed_url, safe="")
    try:
        d = json.loads(fetch(api, timeout=10, tries=1, max_bytes=200_000))
    except Exception as e:  # unavailable post or video: say so, Claude decides
        return f"(could not look up: {str(e)[:60]})"
    text = d.get("title") or " ".join(html.unescape(re.sub(r"<[^>]+>", " ", d.get("html", ""))).split())
    return f"{d.get('author_name', '?')} | {text[:140]}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--curated", type=Path, required=True)
    args = ap.parse_args()
    doc = json.loads(args.curated.read_text())
    items = doc["items"] if isinstance(doc, dict) else doc
    with ThreadPoolExecutor(max_workers=6) as pool:
        found = list(pool.map(lambda it: inspect(it["url"]), items))
    report = []
    for it, f in zip(items, found):
        if f.get("image") and not it.get("image_url"):
            it["image_url"], it["image_kind"] = f["image"], "cover"
        if not it.get("embed_url"):
            pick = (f.get("videos") or f.get("tweets") or [None])[0]
            if pick and svlib.detect_embed(pick):
                it["embed_url"] = pick
        note = describe(it["embed_url"]) if it.get("embed_url") else ""
        if note and svlib.detect_embed(it["embed_url"])[0] == "youtube":
            channel = note.split(" | ")[0].lower().replace(" ", "")
            if channel and channel in urllib.parse.urlsplit(it["url"]).netloc.replace("-", ""):
                note += "  [publisher's own channel: check it is about this story]"
        report.append({"url": it["url"], "title": it["title"], **f, "image_url": it.get("image_url"),
                       "embed_url": it.get("embed_url"), "embed_check": note})
    args.curated.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    (args.curated.parent / "enrich.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    with_img = sum(1 for it in items if it.get("image_url"))
    with_embed = sum(1 for it in items if it.get("embed_url"))
    print(f"{len(items)} stories: {with_img} with an image, {with_embed} with an embed")
    for r in report:
        flag = ("IMG " if r["image_url"] else "    ") + ("EMB " if r["embed_url"] else "    ")
        print(f"  {flag}{r['status'][:28]:<28} {r['title'][:60]}" + (f"\n        embed {r['embed_url']}\n        is    {r['embed_check']}" if r["embed_url"] else "")
              + (f"\n        other candidates: {(r.get('videos') or []) + (r.get('tweets') or [])}" if r["embed_url"] and len((r.get('videos') or []) + (r.get('tweets') or [])) > 1 else ""))
    print(f"wrote {args.curated} and {args.curated.parent / 'enrich.json'}")


if __name__ == "__main__":
    main()
