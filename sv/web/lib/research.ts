// The founders' Research page, as pure functions so `npm test` checks them.
// PRIVATE data: only ever called with what getResearch() returned for an
// unlocked request.
import { RUBRIC } from './nextSteps.ts';
import type { ResearchFinding, ResearchIdea, ResearchOutcome, ResearchRun } from './types.ts';

export interface BoardRow extends ResearchIdea {
  run: { id: string; title: string };
}

/** Every scored idea across the runs, best first. Ties keep the order the
 * runs came in (newest day first, then each day's order). */
export function board(runs: ResearchRun[], only?: { run?: string; atLeast?: number }): BoardRow[] {
  return runs
    .filter((r) => !only?.run || r.id === only.run)
    .flatMap((r) => r.ideas.map((i) => ({ ...i, run: { id: r.id, title: r.title } })))
    .filter((i) => only?.atLeast === undefined || i.total >= only.atLeast)
    .sort((a, b) => b.total - a.total);
}

/** Consecutive findings that share a group, as blocks under one heading. */
export function groupFindings(findings: ResearchFinding[]): { group: string | null; items: ResearchFinding[] }[] {
  const out: { group: string | null; items: ResearchFinding[] }[] = [];
  for (const f of findings) {
    const last = out[out.length - 1];
    if (last && last.group === f.group) last.items.push(f);
    else out.push({ group: f.group, items: [f] });
  }
  return out;
}

export function researchStats(runs: ResearchRun[], cutoff: number) {
  const ideas = runs.flatMap((r) => r.ideas);
  const best = ideas.reduce<ResearchIdea | null>((b, i) => (!b || i.total > b.total ? i : b), null);
  return { runs: runs.length, ideas: ideas.length, atCutoff: ideas.filter((i) => i.total >= cutoff).length, best };
}

/** "3/4/9/5/6/8/4/2", and the same spelled out for a screen reader. */
export function linesText(lines: ResearchIdea['lines']): { short: string; spoken: string } | null {
  if (!lines) return null;
  return {
    short: RUBRIC.map((r) => lines[r.key]).join('/'),
    spoken: RUBRIC.map((r) => `${r.label.toLowerCase()} ${lines[r.key]} of ${r.max}`).join(', '),
  };
}

export const OUTCOME_LABEL: Record<ResearchOutcome, string> = {
  makes_list: 'Makes the list',
  below_cutoff: 'Below the cutoff',
  no: 'No',
  replaced: 'Replaced',
  input: 'Input',
};
