import assert from 'node:assert/strict';
import { test } from 'node:test';

import { band, nextSteps } from './nextSteps.ts';
import type { DeskMover } from './types.ts';

const base: DeskMover = {
  id: 'example-co',
  name: 'Example Co',
  kind: 'company',
  url: 'https://example.com/',
  one_liner: 'A tool that does one job well.',
  summary: null,
  traction: [{ label: 'ARR (company-stated)', value: 'About $108k', source_url: 'https://example.com/yc', as_of: '2026-10-22' }],
  markets_live: ['US'],
  claim_status: 'reported',
  tags: [],
  image_url: null,
  image_kind: null,
  first_added_at: '2026-10-22T00:00:00Z',
  updated_at: '2026-10-22T00:00:00Z',
  news_count: 0,
  latest_news_at: null,
  news_recent: 0,
  status: 'proposed',
  added_by: 'michael',
  notes: { take: 'A private take.', learn: 'A private lesson.', localize: 'A private market note.', updated_at: null },
  score: {
    total: 55,
    lines: { demand: 0, problem: 5, fit: 14, wedge: 7, market: 7, future: 12, moat: 7, whitespace: 3 },
    market: 'Example market',
    verdict: 'A private verdict.',
  },
  stage: 'new',
  votes: [{ voter: 'michael', vote: 1, reason: 'a private reason', at: '2026-10-22T01:00:00Z' }],
  net_votes: 1,
};
const PAGE = 'https://induscore.site/sv/movers/example-co';

test('bands follow the rubric cut-offs', () => {
  assert.deepEqual([39, 40, 54, 55, 69, 70].map((n) => band(n).key), ['drop', 'watch', 'watch', 'interview', 'interview', 'strong']);
});

test('a product gets an REA prompt, a build brief and a score prompt with its facts and our take', () => {
  const [rea, build, score] = nextSteps(base, PAGE);
  assert.deepEqual([rea.key, build.key, score.key], ['rea', 'build', 'score']);
  assert.match(rea.prompt, /reverse-engineer-anything skill \(REA\) on Example Co \(https:\/\/example\.com\/\)/);
  assert.match(rea.prompt, /for Example market/);
  for (const s of [rea, build, score]) {
    assert.match(s.prompt, /About \$108k \(https:\/\/example\.com\/yc, as of 2026-10-22\)/); // every figure with its source and date
    assert.match(s.prompt, /Never put customer names or customer data/);
    assert.ok(s.prompt.includes(PAGE));
  }
  assert.match(build.prompt, /55\/100 for Example market \(worth interviews\)/);
  assert.match(build.prompt, /michael up \("a private reason"\)/);
  assert.match(score.prompt, /ingest\.py notes example-co score\.json/);
  assert.equal(score.title, 'Score it again');
});

test('a skill is taken apart from its source, not with REA; an unscored mover asks for a market', () => {
  const skill = { ...base, kind: 'skill' as const, score: null, notes: { take: null, learn: null, localize: null, updated_at: null }, votes: [] };
  const [rea, , score] = nextSteps(skill, PAGE);
  assert.doesNotMatch(rea.prompt, /REA\)/);
  assert.match(rea.prompt, /install_skill\.py/);
  assert.match(rea.prompt, /a market you name first/);
  assert.equal(score.title, 'Score it');
  assert.match(score.prompt, /Not scored yet/);
});
