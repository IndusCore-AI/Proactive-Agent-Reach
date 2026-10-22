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
  rank?: number;
  feed_date?: string;
  mentions?: Mention[];
}

export interface RunSummary {
  id: string;
  status: 'complete' | 'partial' | 'failed';
  started_at: string;
  finished_at: string | null;
  sources: { source: string; ok: boolean; kept: number | null; error: string | null }[];
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
}
