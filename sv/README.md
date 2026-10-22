# Keeping Up with Silicon Valley

A daily, source-linked feed of startup funding, launches, founder discussions and VC news, published at
**https://induscore.site/sv**. Stories are collected and curated once a day by Claude Code (either founder's),
stored in a dedicated database on the IndusCore prod VM, and served by a Next.js site on Vercel.

This directory is self-contained; nothing outside `sv/` belongs to it, and it does not touch the Agent-Reach
package that shares the repository.

```
sv/
  web/     Next.js 15 site (Vercel project induscore-sv, basePath /sv)
  api/     FastAPI read + ingest API and SQL migrations (runs on the prod VM)
  skill/   the Claude Code skill /aggregate-silicon-valley (shipped to both laptops via teamctx)
  ops/     VM setup, deploy, tunnel, skill publishing
  tests/   unit tests for the skill's pure logic (stdlib only)
```

## How it fits together

```
Claude Code (Pulkit or Michael)                         visitors, crawlers
  /aggregate-silicon-valley                                  │
  collect.py ── RSS / HN Algolia / YC Launches JSON          ▼
  curate (Claude) ── curated.json                   induscore.site  (Vercel project ai-native-crm-website)
  ingest.py ──POST /sv/api/ingest/* ───────────────▶   rewrite /sv/* ─▶ induscore-sv (Next.js, Vercel)
                                                                           │ server-side only, read token
                                                                           ▼
                                           ntfy topic (HMAC-signed tunnel URL) ◀── discovery
                                                                           │
                                       Cloudflare quick tunnel ─▶ prod VM 127.0.0.1:8793 (FastAPI)
                                                                           ▼
                                                     Postgres 17, database induscore_sv (role sv_app)
```

- **URL**: `induscore.site/sv`. The marketing project rewrites `/sv` and `/sv/:path*` to
  `https://induscore-sv.vercel.app/sv/...` (multi-zone). Subdomains were not used because `*.induscore.site`
  is the tenant wildcard of the IndusCore app.
- **Database**: `induscore_sv` on the prod VM's Postgres 17, owned by role `sv_app`, CONNECT revoked from
  PUBLIC, listening on localhost only. Separate from every IndusCore database. Test copy: `induscore_sv_test`.
- **VM → Vercel**: the VM only admits SSH, so the API is exposed by its own Cloudflare quick tunnel. Its URL
  changes when the tunnel restarts; `ops/run-tunnel.sh` announces each new URL on an ntfy topic, signed with
  HMAC-SHA256, and the site trusts only a correctly signed `*.trycloudflare.com` URL (`web/lib/api.ts`).
  Same pattern as teamctx.
- **Freshness**: pages render per request from Next's data cache (5 minutes); every successful ingest call
  clears that cache, so new stories appear on the next request without a redeploy.
- **No scheduler**: nothing collects content on its own. The VM cron entries tagged `keeping-up-sv-*` only
  keep the API and tunnel alive and re-announce the tunnel URL every 6 hours (ntfy keeps messages ~12 hours).

## Daily aggregation

In Claude Code: `/aggregate-silicon-valley` (today, Pacific time) or `/aggregate-silicon-valley 2026-10-22`.
The skill (`skill/aggregate-silicon-valley/SKILL.md`) collects, has Claude curate, persists, then verifies
the database and the public page. Reruns and backfills are safe: stories upsert by canonical URL and each
story belongs to exactly one edition.

One-time per person: an ingest token in `~/.config/keeping-up-sv/ingest.env` (command in SKILL.md). Tokens
are per person (`manage.py issue-token <name>`), stored only as sha256 on the VM, revocable
(`manage.py revoke-token <name>`), and the run records who ran it.

### Sources

Configured in `skill/aggregate-silicon-valley/sources.json` (23 enabled). Hacker News (Algolia API), YC
Launches (JSON), Product Hunt, TechCrunch, Crunchbase News, Techmeme, StrictlyVC, GeekWire, SiliconANGLE,
The Verge, Wired, The Next Web, Sequoia, a16z, Lenny's Newsletter, Not Boring, Tomasz Tunguz, Latent Space,
OpenAI, Google AI, Hugging Face, GitHub Blog, Reddit (RSS). Limits:

- **Reddit** rate-limits anonymous readers (429); best effort, a failure is shown on the edition.
- **X/Twitter** has no open read access; posts are embedded with X's widget only when another source links
  to them. No X discovery.
- **Stratechery, SemiAnalysis, SaaStr** answer 403 to automated readers; disabled, not worked around.
- YouTube is embed-only (click to load, youtube-nocookie.com).

## Configuration

| Where | Name | What |
| --- | --- | --- |
| Vercel `induscore-sv` (prod + preview) | `SV_READ_TOKEN` | read token; its sha256 is `SV_READ_TOKEN_SHA256` on the VM |
| Vercel | `SV_ANNOUNCE_SECRET`, `SV_NTFY_TOPIC` | verify the signed tunnel URL; same values as the VM |
| Vercel (optional) | `SV_API_URL` | fallback API URL when no announcement is found |
| VM `~/.config/keeping-up-sv/env` (600) | `SV_DATABASE_URL`, `SV_TEST_DATABASE_URL`, `SV_PORT`, `SV_READ_TOKEN_SHA256`, `SV_ANNOUNCE_SECRET`, `SV_NTFY_TOPIC` | written by `ops/vm-setup.sh` |
| Each laptop `~/.config/keeping-up-sv/ingest.env` (600) | `SV_INGEST_TOKEN` (+ optional `SV_BASE_URL`) | personal ingest token |

Rotating the read token: generate one locally, `vercel env add SV_READ_TOKEN production` from stdin, put its
sha256 into the VM env file, `bash sv/ops/deploy-vm.sh main`, redeploy the site.

## Deploying

- **API** (from either laptop): `SV_VM=<vm ssh target> SV_VM_KEY=<path to the team key> bash sv/ops/deploy-vm.sh main`.
  The VM host and key are in teamctx (prod VM workflow), not in this public repo.
  Clones/pulls into `~/keeping-up-sv` on the VM, applies migrations, restarts tmux `keeping-up-sv:api`
  (the tunnel keeps its URL).
- **Site**: `cd sv/web && vercel deploy --prod` (project `induscore-sv`, linked by `vercel link --project induscore-sv`).
  No Git integration on purpose: upstream Agent-Reach syncs must not trigger site builds.
- **Skill**: after changing `skill/`, `SV_VM=... bash sv/ops/publish-skill.sh`, then `ctx update` on each laptop.

## Tests

```bash
python3 -m pytest -q sv/tests                                   # skill logic, no network
cd sv/web && npm test && npx tsc --noEmit && npx next build     # site
# API, on the VM against induscore_sv_test:
ssh <vm> 'cd ~/keeping-up-sv/sv/api && set -a && . ~/.config/keeping-up-sv/env && set +a && .venv/bin/python -m pytest -q tests'
```

## SEO

Server-rendered pages; unique titles, descriptions and canonicals; `CollectionPage` + `ItemList` on editions,
`WebPage` + `isBasedOn` (the original source) + `BreadcrumbList` on stories, `AboutPage` on the methodology.
`/sv/sitemap.xml` (listed in the apex robots.txt) holds hub pages, every edition, topics with at least three
stories, and every story. Filtered views, search, empty dates and thin topics are `noindex, follow`.
`/sv/feed.xml` (RSS) and `/sv/llms.txt` exist for readers and assistants. Wrong story slugs 308 to the
canonical slug; invalid or future dates 404.

## Analytics

Vercel Web Analytics of the `induscore.site` project (`ai-native-crm-website`), which already has it enabled:
the zone loads `/_vercel/insights/script.js` from the host root and reports `/sv/...` paths
(`components/SiteAnalytics.tsx`, `@vercel/analytics/react` 1.5.0). Search terms are stripped before
sending; no cookies. Filter the dashboard by path `/sv`.

## Troubleshooting

- `https://induscore.site/sv/api/health` shows whether the site reaches the API and the latest edition.
- On the VM: `tmux ls | grep keeping-up-sv`; `bash ~/keeping-up-sv/sv/ops/start.sh`; logs in
  `~/.local/state/keeping-up-sv/logs/`; current tunnel in `~/.local/state/keeping-up-sv/tunnel_url`.
- A run that died mid-way stays `running` and is marked failed after 3 hours; rerun the date.

## Backups

`induscore_sv` is small (metadata only). Back it up with
`sudo -u postgres pg_dump -Fc induscore_sv > induscore_sv-$(date +%F).dump` and restore with `pg_restore -d
induscore_sv`. The schema is reproducible from `api/migrations/` (`manage.py migrate`), and every story links
to its original, so losing the database loses the archive's curation, not the sources.
