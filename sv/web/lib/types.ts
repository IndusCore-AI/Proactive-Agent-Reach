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

/** PRIVATE: only ever fetched for a founders-unlocked request (lib/api.ts getPrivateNotes). */
export interface MoverNotes {
  take: string | null;
  learn: string | null;
  localize: string | null;
  updated_at: string;
}
