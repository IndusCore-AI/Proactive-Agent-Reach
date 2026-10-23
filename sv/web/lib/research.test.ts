import assert from 'node:assert/strict';
import { test } from 'node:test';

import { board, groupFindings, linesText, researchStats } from './research.ts';
import type { ResearchIdea, ResearchRun } from './types.ts';

const idea = (idea: string, total: number, extra: Partial<ResearchIdea> = {}): ResearchIdea => ({
  position: 0, idea, market: 'Example market', total, lines: null, note: null, mover: null, ...extra,
});
const run = (id: string, ideas: ResearchIdea[]): ResearchRun => ({
  id, title: id, run_date: '2026-10-22', outcome: 'makes_list', verdict: 'v', summary: null, method: null,
  findings: [], sources: [], refs: [], updated_by: 'michael', updated_at: '2026-10-22T00:00:00Z', ideas,
});
const RUNS = [run('a', [idea('a1', 49), idea('a2', 31)]), run('b', [idea('b1', 55), idea('b2', 49), idea('b3', 22)])];

test('the board ranks every idea, ties in run order, and filters by run or cutoff', () => {
  assert.deepEqual(board(RUNS).map((r) => r.idea), ['b1', 'a1', 'b2', 'a2', 'b3']);
  assert.deepEqual(board(RUNS, { run: 'a' }).map((r) => r.idea), ['a1', 'a2']);
  assert.deepEqual(board(RUNS, { atLeast: 40 }).map((r) => [r.idea, r.run.id]), [['b1', 'b'], ['a1', 'a'], ['b2', 'b']]);
});

test('stats count runs, ideas and those at the cutoff, and name the best', () => {
  const s = researchStats(RUNS, 40);
  assert.deepEqual([s.runs, s.ideas, s.atCutoff, s.best?.idea], [2, 5, 3, 'b1']);
  assert.equal(researchStats([], 40).best, null);
});

test('findings in the same group share one heading', () => {
  const g = groupFindings([
    { group: null, title: 'A', text: '1' }, { group: null, title: null, text: '2' },
    { group: 'How they grew', title: null, text: '3' }, { group: 'How they grew', title: null, text: '4' },
  ]);
  assert.deepEqual(g.map((b) => [b.group, b.items.length]), [[null, 2], ['How they grew', 2]]);
});

test('line scores read in rubric order, and out loud', () => {
  const lines = { demand: 3, problem: 4, fit: 9, wedge: 5, market: 6, future: 8, moat: 4, whitespace: 2 };
  assert.deepEqual(linesText(lines)?.short, '3/4/9/5/6/8/4/2');
  assert.match(linesText(lines)!.spoken, /^demand evidence 3 of 25, problem sharpness 4 of 10/);
  assert.equal(linesText(null), null);
});
