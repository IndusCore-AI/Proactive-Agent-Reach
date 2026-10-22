import assert from 'node:assert/strict';
import { test } from 'node:test';

import { addDays, idFromSlug, isIsoDate, slugify, storyPath, todayPT } from './format.ts';

test('isIsoDate accepts real dates only', () => {
  assert.equal(isIsoDate('2026-10-22'), true);
  assert.equal(isIsoDate('2026-02-30'), false);
  assert.equal(isIsoDate('2026-10-22x'), false);
  assert.equal(isIsoDate('../etc'), false);
});

test('todayPT uses Pacific time', () => {
  assert.equal(todayPT(new Date('2026-10-22T06:30:00Z')), '2026-10-21');
  assert.equal(todayPT(new Date('2026-10-22T08:00:00Z')), '2026-10-22');
});

test('story paths round-trip to the id', () => {
  const p = storyPath({ id: 'abcdefgh2345', title: 'Acme raises $12M — Series A & more!' });
  assert.equal(p, '/story/acme-raises-12m-series-a-and-more-abcdefgh2345');
  assert.equal(idFromSlug(p.slice(7)), 'abcdefgh2345');
  assert.equal(idFromSlug('abcdefgh2345'), 'abcdefgh2345');
  assert.equal(idFromSlug('no-id-here'), null);
  assert.equal(slugify('日本語'), '');
  assert.equal(storyPath({ id: 'abcdefgh2345', title: '日本語' }), '/story/abcdefgh2345');
});

test('addDays crosses months', () => {
  assert.equal(addDays('2026-10-31', 1), '2026-11-01');
  assert.equal(addDays('2026-03-01', -1), '2026-02-28');
});
