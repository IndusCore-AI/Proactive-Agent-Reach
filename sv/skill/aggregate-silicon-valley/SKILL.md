---
name: aggregate-silicon-valley
description: >
  Run the daily aggregation for Keeping Up with Silicon Valley (induscore.site/sv): collect startup, funding,
  launch, founder and VC stories from the configured sources, curate them, persist them to the VM database
  through the site's ingest API, and verify they are live. Use when the user says /aggregate-silicon-valley
  [YYYY-MM-DD], "run today's Silicon Valley feed", "aggregate the SV feed", "backfill the feed for <date>",
  "rerun the startup feed", or asks why an edition is missing or partial. Not for changing the site's code.
---

# aggregate-silicon-valley

You are the orchestrator of one edition of **Keeping Up with Silicon Valley** (https://induscore.site/sv).
Scripts do the fetching and the writing; you do the judgment: which stories matter, what kind each is,
which duplicates are the same event, and a one-line context note grounded in the source. This skill is
the **only** way stories get into the feed: there is no cron job or hosted agent, by design.

Paths below are relative to this skill's directory (`~/.claude/skills/aggregate-silicon-valley/` when
installed by teamctx). Use `python3 -I` so nothing from the current directory is imported.

## One-time setup (per person)

1. You need an ingest token. If `python3 -I scripts/ingest.py --check` says "No ingest token", get one
   from the VM (each founder has their own; issuing a new one replaces your old one):

   ```bash
   ssh <vm> 'cd ~/keeping-up-sv/sv/api && set -a && . ~/.config/keeping-up-sv/env && set +a && .venv/bin/python manage.py issue-token <your-name>' \
     | sed 's/^/SV_INGEST_TOKEN=/' > ~/.config/keeping-up-sv/ingest.env && chmod 600 ~/.config/keeping-up-sv/ingest.env
   ```

   `<vm>` is the prod VM's ssh target (host and key are in teamctx, the prod VM workflow). Create
   `~/.config/keeping-up-sv/` first (`mkdir -p -m 700`). Never paste the token into chat, teamctx or git.
2. `python3 -I scripts/ingest.py --check` must print `ingest token: ok`.

## The run

**0. Date.** Use the date the user gave (YYYY-MM-DD). Otherwise today in Pacific time:
`python3 -I -c "import sys; sys.path.insert(0,'scripts'); import svlib; print(svlib.today_pt())"`.
Future dates are refused. An edition for date D covers stories published in the 48 hours before the end
of D (Pacific); a story already featured in another edition is never repeated, so reruns and backfills
are safe.

**1. Collect.**
```bash
python3 -I scripts/collect.py --date D --out "${TMPDIR:-/tmp}/keeping-up-sv/D"
```
It prints each source's status. Failed sources are expected sometimes (Reddit rate limits anonymous
readers); the run continues and the failure is recorded on the edition. Do not retry a failed source more
than once, and never work around a block (403, robots, login walls).

**2. Curate.** Read `candidates.json` (ranked by a heuristic `score`). Write `curated.json` in the same
directory: `{"items": [...]}`. Aim for the best 25–45 stories; on a quiet day fewer is right. Never
add a story, number, date or link that is not in the candidates or in a page you actually opened.

For each kept candidate, start from its fields and fix them:

- **Keep** stories about startups, funding, acquisitions, launches, founders, investors, AI/dev tools/infra
  and other technology businesses, and the big-company moves that shape them. **Drop** general politics,
  celebrity, sports, consumer deals, routine patch releases, and HN posts with no startup or technology-business
  angle. Prefer the original publisher's article over a re-write.
- **Same event, different headlines** (e.g. TechCrunch and SiliconANGLE both on one round): keep the best
  article as the item and put the others in its `mentions` as `{"url", "source", "label"}` (label = the
  publication's name). Keep existing Hacker News/Techmeme mentions with their points/comments.
- `category`: `funding` (a round or new fund, as reported), `acquisition`, `launch` (a product, model or
  company launch), `news`, `discussion` (Ask HN, Reddit threads, debates), `analysis` (VC theses, essays,
  predictions, market maps).
- `claim_status`: `confirmed` when the company itself announced it (its blog, its launch page, YC Launch,
  Product Hunt maker post); `reported` when a publication reported it, including "sources say";
  `unverified` for claims in posts or threads (growth numbers, revenue, "we hit $1M ARR"); `opinion` for
  analysis and predictions.
- `funding` (funding items only, and only what the source states): `{"company", "round", "amount",
  "investors": [...]}`. `funding_hint` in the candidate is a regex guess; check it against the title and
  excerpt and drop anything you cannot see there. No funding object on an `unverified` item.
- `tags`: up to 6 lowercase slugs from: ai, ai-agents, devtools, infra, chips, robotics, fintech, crypto,
  security, climate, health, defense, consumer, enterprise, open-source, vc, ipo, yc, m-and-a, plus a few
  specific ones when they recur (e.g. `openai`, `nvidia`). Keep the vocabulary small so topic pages fill up.
- `title`: the source's headline. You may shorten a very long Techmeme summary headline to its first
  clause; never change its meaning or add claims.
- `summary` (optional, max 1–2 sentences, ≤ 400 chars): why it matters, using only facts in the title or
  excerpt (e.g. who led the round, what the product does). Leave it out rather than guess.
- `excerpt`: keep the candidate's (the source's own words). Do not write your own text into `excerpt`.
- `score`: start from the candidate's score; move it by at most ±20 and say why in
  `score_detail.why` (one plain sentence a reader would understand, e.g. "Largest disclosed AI round this
  week; covered by three outlets."). Keep the rest of `score_detail`.
- `embed_url`: only if the story *is* an X post or YouTube video (the site uses the platforms' own embeds).
- Copy `url`, `source`, `source_name`, `published_at`, `author`, `mentions` from the candidate. Drop the
  helper fields (`id`, `found_in`, `weight`, `relevant`, `engagement`, `funding_hint`, `extra`,
  `engagement_self`); the ingest script ignores unknown fields anyway. Keep `image_url` and `image_kind`
  when the candidate has them (feed images, YC logos).

Writing `curated.json` with a short Python snippet that loads candidates, applies your decisions by
`id`, and dumps the result is the most reliable way for 30+ items.

**3. Pictures and embeds.**
```bash
python3 -I scripts/enrich.py --curated "$DIR/curated.json"
```
It opens each curated story's own page once (robots.txt respected) and adds `image_url` (the page's
preview image, a link to the publisher's file, never a copy) and `embed_url` (a YouTube video or an X
post the publisher embedded or cited in the article). Review every embed it prints: each line shows the
post's author and opening words, or the video's channel and title. Keep it only if it is about the story
(the company's own announcement, the founder's post, the official advisory, the product demo). Replace it
with a better "other candidate" or remove `embed_url` for that item in `curated.json` when it is
off-topic: a publisher's promo for its own podcast, a reply or tribute, an unrelated post. Never invent an
embed URL; only use ones the script found or that the source itself links.

**4. Persist and verify.**
```bash
python3 -I scripts/ingest.py --date D --curated "$DIR/curated.json" --sources "$DIR/sources.json"
```
It starts a run, sends the items, finishes the run with every source's status (`complete` only when every
source worked and nothing was rejected, otherwise `partial`), then checks the database holds every story
and the public page `https://induscore.site/sv/D` shows the top ones. Exit code 0 means both checks passed.
If items are rejected, read the reason, fix `curated.json`, and rerun the same command: reruns update in
place and never duplicate.

**5. Report** to the user, from `report.json`, without rounding up: edition date and URL, stories in the
edition, inserted/updated/merged/rejected, sources that worked and those that failed (with the error),
whether the database and page checks passed, and the run status (`complete` or `partial`). Say plainly if
anything failed.

## Movers to watch

`https://induscore.site/sv/movers` lists companies, apps and skills gaining traction, kept apart from the
daily news. **Add or change a mover only when a founder asks you to.** The daily run never creates one.

**In the daily run**, after step 4: `python3 -I scripts/ingest.py movers --list` prints the existing movers.
When a story you just published is clearly about one of them (the company raised, the app launched in a new
market, the skill shipped a release), link it:
`python3 -I scripts/ingest.py link <mover-id> <story-url> [<story-url> ...]`. Link only clear matches; a
passing mention is not one. Missing stories are reported, never created.

**When a founder asks to add or update one**, write a JSON file under `${TMPDIR:-/tmp}/keeping-up-sv/`
(never in a repo, teamctx or chat) and run `python3 -I scripts/ingest.py movers <file.json>`:

```json
{"movers": [{
  "id": "example-robotics", "name": "Example Robotics", "kind": "company",
  "url": "https://example.com", "one_liner": "Robot arms for small kitchens (max 200 chars).",
  "summary": "Neutral facts only, max 800 chars.",
  "traction": [{"label": "Restaurants live", "value": "120", "source_url": "https://example.com/blog/120", "as_of": "2026-10-01"}],
  "markets_live": ["US", "UK"], "claim_status": "confirmed", "tags": ["robotics"],
  "image_url": "https://example.com/logo.png", "image_kind": "logo",
  "notes": {"take": "How it helps us", "learn": "What to learn", "localize": "Where to localize"},
  "item_urls": ["https://techcrunch.com/..."]
}]}
```

- Everything except `notes` is **public** and indexed: what it is, its traction, its sources. Every traction
  line needs a `source_url` (https) you actually opened and the date the figure was true; no source, no line
  (at most 8). `claim_status` is `confirmed` (the company states it), `reported` or `unverified`.
- `notes` is the founders' **private** take; it is shown only after the founders' unlock and never in public
  HTML, the sitemap, RSS, llms.txt or JSON-LD. Write it only from what the founder told you. Leaving a note
  field out keeps what is stored; `null` clears it.
- Reruns update by `id`. The script checks the file first, then verifies every mover is stored and that its
  public page shows the name and **none** of the note text; exit code 0 means both passed.
- `python3 -I scripts/ingest.py archive <mover-id>` stops watching one (it leaves the site; the founder can
  restore it by sending it again with `"status": "watching"`).

## When something is wrong

- `could not start a run: HTTP 502` / `feed API unreachable`: the VM API or its tunnel is down. On the VM:
  `tmux ls | grep keeping-up-sv`, `bash ~/keeping-up-sv/sv/ops/start.sh`, logs in
  `~/.local/state/keeping-up-sv/logs/`. The site rediscovers a new tunnel URL by itself within minutes.
- `HTTP 403 invalid ingest token`: your token was rotated or revoked; redo the one-time setup.
- A run that died midway stays `running` and is marked failed after 3 hours; just rerun the date.
- Page check failed but DB check passed: the page cache refreshes within 5 minutes; open the page again.

More: `sv/README.md` in https://github.com/gaurpulkit/Proactive-Agent-Reach and the teamctx items tagged
`keeping-up-sv`.
