// Pure helpers shared by pages, the sitemap and the feed. No server-only
// imports here, so `npm test` can run them with node --test.
import type { Category, ClaimStatus, Item, MoverKind } from './types.ts';

export const SITE_ORIGIN = 'https://induscore.site';
export const BASE_PATH = '/sv';
export const SITE_URL = `${SITE_ORIGIN}${BASE_PATH}`;
export const SITE_NAME = 'Keeping Up with Silicon Valley';
export const TAGLINE = 'What startups are building, funding, launching and arguing about, gathered every day from the sources that break it.';
export const TZ = 'America/Los_Angeles';
export const FIRST_EDITION = '2026-01-01';

export const CATEGORIES: { key: Category; label: string; plural: string }[] = [
  { key: 'funding', label: 'Funding', plural: 'Funding rounds' },
  { key: 'acquisition', label: 'Acquisition', plural: 'Acquisitions' },
  { key: 'launch', label: 'Launch', plural: 'Launches' },
  { key: 'news', label: 'News', plural: 'News' },
  { key: 'discussion', label: 'Discussion', plural: 'Discussions' },
  { key: 'analysis', label: 'Analysis', plural: 'Analysis and trends' },
];
export const CATEGORY_LABEL = Object.fromEntries(CATEGORIES.map((c) => [c.key, c.label])) as Record<Category, string>;

export const CLAIM_LABEL: Record<ClaimStatus, string> = {
  confirmed: 'Confirmed by the company',
  reported: 'Reported',
  unverified: 'Unverified claim',
  opinion: 'Opinion',
};

export const MOVER_KINDS: { key: MoverKind; label: string; plural: string }[] = [
  { key: 'company', label: 'Company', plural: 'Companies' },
  { key: 'app', label: 'App', plural: 'Apps' },
  { key: 'skill', label: 'Skill', plural: 'Skills' },
];
export const MOVER_KIND_LABEL = Object.fromEntries(MOVER_KINDS.map((k) => [k.key, k.label])) as Record<MoverKind, string>;
export const MOVER_ID_RE = /^[a-z0-9][a-z0-9-]{1,59}$/;

/** The ?kind= filter on /movers, or undefined for anything unrecognised. */
export function moverKind(v: string | string[] | undefined): MoverKind | undefined {
  const k = Array.isArray(v) ? v[0] : v;
  return MOVER_KINDS.some((x) => x.key === k) ? (k as MoverKind) : undefined;
}

export function moverPath(id: string): string {
  return `/movers/${id}`;
}

export const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** A real calendar date in YYYY-MM-DD form (rejects 2026-02-30). */
export function isIsoDate(s: string): boolean {
  if (!DATE_RE.test(s)) return false;
  const d = new Date(`${s}T12:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

/** Today's date in Pacific time, as YYYY-MM-DD. */
export function todayPT(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
}

export function longDate(iso: string): string {
  return new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
    .format(new Date(`${iso}T12:00:00Z`));
}

export function shortDate(iso: string): string {
  return new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric' })
    .format(new Date(`${iso}T12:00:00Z`));
}

export type TimeStyle = 'datetime' | 'time' | 'date';

const TIME_STYLE: Record<TimeStyle, Intl.DateTimeFormatOptions> = {
  datetime: { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' },
  time: { hour: 'numeric', minute: '2-digit' },
  date: { month: 'short', day: 'numeric', year: 'numeric' },
};

/** A moment in `timeZone`, or the runtime's own zone when left out: "Oct 21,
 * 7:05 PM EDT", "7:05 PM EDT" or "Oct 21, 2026". Pacific reads "PT", exactly
 * like timePT, so the server's text and a Pacific viewer's text are the same. */
export function formatMoment(ts: string, style: TimeStyle, timeZone?: string): string {
  const opts: Intl.DateTimeFormatOptions = { ...TIME_STYLE[style], ...(timeZone ? { timeZone } : {}) };
  if (style === 'date') return new Intl.DateTimeFormat('en-US', opts).format(new Date(ts));
  return new Intl.DateTimeFormat('en-US', { ...opts, timeZoneName: 'short' })
    .formatToParts(new Date(ts))
    .map((p) => (p.type === 'timeZoneName' && /^P[SD]T$/.test(p.value) ? 'PT' : p.value))
    .join('');
}

/** "Oct 21, 4:05 PM PT" for a timestamp. */
export function timePT(ts: string): string {
  return formatMoment(ts, 'datetime', TZ);
}

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function slugify(title: string): string {
  return title
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
    .replace(/-+$/g, '');
}

export function storyPath(item: Pick<Item, 'id' | 'title'>): string {
  const slug = slugify(item.title);
  return `/story/${slug ? `${slug}-` : ''}${item.id}`;
}

/** The item id at the end of a story slug, or null. */
export function idFromSlug(slug: string): string | null {
  const m = /(?:^|-)([a-z2-7]{12})$/.exec(slug);
  return m ? m[1] : null;
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

export function compactNumber(n: number): string {
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n);
}

/** One line of funding facts, only what the source stated. */
export function fundingLine(f: NonNullable<Item['funding']>): string {
  const parts = [f.company, f.round, f.amount].filter(Boolean) as string[];
  let line = parts.join(' · ');
  if (f.investors?.length) line += ` · with ${f.investors.slice(0, 4).join(', ')}${f.investors.length > 4 ? ' and others' : ''}`;
  return line;
}

export function tagLabel(tag: string): string {
  const special: Record<string, string> = {
    ai: 'AI', yc: 'Y Combinator', vc: 'Venture capital', devtools: 'Developer tools', saas: 'SaaS',
    'open-source': 'Open source', llm: 'LLMs', fintech: 'Fintech', infra: 'Infrastructure', b2b: 'B2B',
    ipo: 'IPOs', 'm-and-a': 'M&A', gpu: 'GPUs', biotech: 'Biotech', 'ai-agents': 'AI agents',
  };
  return special[tag] ?? tag.split('-').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

export function abs(path: string): string {
  return `${SITE_URL}${path === '/' ? '' : path}`;
}
