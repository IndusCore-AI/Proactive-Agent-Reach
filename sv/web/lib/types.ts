export type Category = 'funding' | 'acquisition' | 'launch' | 'news' | 'discussion' | 'analysis';
export type ClaimStatus = 'confirmed' | 'reported' | 'unverified' | 'opinion';

export interface Mention {
  url: string;
  source: string;
  label: string;
  points: number | null;
  comments: number | null;
  observed_at: string;
}

export interface Funding {
  company: string;
  round?: string;
  amount?: string;
  amount_usd?: number;
  investors?: string[];
}

export interface Item {
  id: string;
  url: string;
  source: string;
  source_name: string;
  title: string;
  excerpt: string | null;
  summary: string | null;
  author: string | null;
  published_at: string | null;
  discovered_at: string;
  updated_at: string;
  category: Category;
  tags: string[];
  claim_status: ClaimStatus;
  funding: Funding | null;
  embed: { type: 'x' | 'youtube'; ref: string } | null;
  score: number;
  image_url?: string | null;
  image_kind?: 'cover' | 'logo' | null;
  rank?: number;
  feed_date?: string;
  mentions?: Mention[];
}

export interface RunSummary {
  id: string;
  status: 'complete' | 'partial' | 'failed';
  started_at: string;
  finished_at: string | null;
  sources: { source: string; name?: string | null; ok: boolean; fetched?: number | null; kept: number | null; error: string | null }[];
}

export interface Feed {
  date: string | null;
  total: number;
  items: Item[];
  facets: {
    categories?: Partial<Record<Category, number>>;
    sources?: Record<string, { name: string; n: number }>;
  };
  run: RunSummary | null;
  prev: string | null;
  next: string | null;
}

export interface ItemDetail extends Item {
  score_detail: Record<string, unknown> | null;
  related: Item[];
  /** Movers this story feeds (public facts only: id, name, kind). */
  movers?: MoverRef[];
}

export type MoverKind = 'company' | 'app' | 'skill';
export type MoverClaim = 'confirmed' | 'reported' | 'unverified';

/** One traction fact as its source states it, with the date it was true. */
export interface Traction {
  label: string;
  value: string;
  source_url: string;
  as_of: string;
}

/** A mover's public facts. The founders' take is a separate type, fetched separately. */
export interface Mover {
  id: string;
  name: string;
  kind: MoverKind;
  url: string;
  one_liner: string;
  summary: string | null;
  traction: Traction[];
  markets_live: string[];
  claim_status: MoverClaim;
  tags: string[];
  image_url: string | null;
  image_kind: 'cover' | 'logo' | null;
  first_added_at: string;
  updated_at: string;
  news_count: number;
  latest_news_at: string | null;
  /** Stories published in the last 14 days: what "Trending" sorts by. */
  news_recent: number;
}

export interface MoverDetail extends Mover {
  items: Item[];
}

export interface MoverList {
  total: number;
  movers: Mover[];
  facets: { kinds?: Partial<Record<MoverKind, number>> };
}

export interface MoverRef {
  id: string;
  name: string;
  kind: MoverKind;
}

/** A public line on /movers/updates: a mover added to the list, or new stories pointing at one. */
export interface MoverUpdate {
  id: number;
  at: string;
  kind: 'added' | 'news';
  mover_id: string;
  name: string;
  mover_kind: MoverKind;
  count: number | null;
}

// ---------------------------------------------------------------- PRIVATE
// Everything below is only ever fetched for a founders-unlocked request
// (lib/api.ts, the desk* functions), never cached, never rendered otherwise.

export type MoverStatus = 'proposed' | 'watching' | 'archived';
export type MoverStage = 'new' | 'researching' | 'building' | 'passed';
export type RubricLine = 'demand' | 'problem' | 'fit' | 'wedge' | 'market' | 'future' | 'moat' | 'whitespace';

export interface MoverNotes {
  take: string | null;
  learn: string | null;
  localize: string | null;
  updated_at: string | null;
}

/** The office-hours rubric for the localized idea, in one named market. */
export interface Score {
  total: number;
  lines: Record<RubricLine, number>;
  market: string;
  verdict: string | null;
  scored_at?: string;
  scored_by?: string;
}

export interface Vote {
  voter: string;
  vote: 1 | -1;
  reason: string | null;
  at: string;
}

export interface DeskMover extends Mover {
  status: MoverStatus;
  added_by: string;
  notes: MoverNotes;
  score: Score | null;
  stage: MoverStage;
  votes: Vote[];
  net_votes: number;
}

export interface DeskEvent {
  id: number;
  at: string;
  kind: 'proposed' | 'added' | 'news' | 'vote' | 'stage' | 'scored' | 'archived';
  actor: string;
  detail: Record<string, unknown>;
}

export interface DeskDetail extends DeskMover {
  items: Item[];
  events: DeskEvent[];
}

export interface DeskList {
  movers: DeskMover[];
  facets: {
    status: Partial<Record<MoverStatus, number>>;
    kind: Partial<Record<MoverKind, number>>;
    stage: Partial<Record<MoverStage, number>>;
    /** Stages over every mover not archived, for the desk's tiles. */
    stage_active: Partial<Record<MoverStage, number>>;
  };
}

export interface DeskUpdate extends DeskEvent {
  private: boolean;
  mover_id: string;
  name: string;
  mover_kind: MoverKind;
  status: MoverStatus;
}
