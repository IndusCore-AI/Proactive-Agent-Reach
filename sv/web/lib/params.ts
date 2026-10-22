import { CATEGORIES } from './format';
import type { Category } from './types';

type SP = Record<string, string | string[] | undefined>;

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

/** Filters from the query string; anything unrecognised is dropped. */
export function readFilters(sp: SP): { category?: Category; source?: string; page: number } {
  const c = one(sp.category);
  const s = one(sp.source);
  const p = Number(one(sp.page) ?? '1');
  return {
    category: CATEGORIES.some((x) => x.key === c) ? (c as Category) : undefined,
    source: s && /^[a-z0-9][a-z0-9-]{0,31}$/.test(s) ? s : undefined,
    page: Number.isInteger(p) && p >= 1 && p <= 50 ? p : 1,
  };
}

export function hasFilters(sp: SP): boolean {
  return ['category', 'source', 'page'].some((k) => sp[k] !== undefined);
}
