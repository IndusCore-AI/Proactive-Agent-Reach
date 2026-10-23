import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  MOVER_ID_RE, addDays, formatMoment, idFromSlug, isIsoDate, moverKind, moverPath, shortDate, slugify, storyPath, timePT, todayPT,
} from './format.ts';

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

test('mover kind filter and paths', () => {
  assert.equal(moverKind('app'), 'app');
  assert.equal(moverKind(['skill', 'app']), 'skill');
  assert.equal(moverKind('person'), undefined);
  assert.equal(moverKind(undefined), undefined);
  assert.equal(moverPath('example-robotics'), '/movers/example-robotics');
  assert.equal(MOVER_ID_RE.test('example-robotics'), true);
  assert.equal(MOVER_ID_RE.test('../etc'), false);
  assert.equal(MOVER_ID_RE.test('x'), false);
});

test('a moment reads in the given zone, and Pacific matches the server text exactly', () => {
  const ts = '2026-10-23T03:14:00Z';
  assert.match(timePT(ts), /^Oct 22, 8:14\sPM PT$/u);
  assert.equal(formatMoment(ts, 'datetime', 'America/Los_Angeles'), timePT(ts));
  assert.match(formatMoment(ts, 'datetime', 'America/New_York'), /^Oct 22, 11:14\sPM EDT$/u);
  assert.match(formatMoment(ts, 'datetime', 'Asia/Kolkata'), /^Oct 23, 8:44\sAM GMT\+5:30$/u);
  assert.match(formatMoment(ts, 'time', 'America/Los_Angeles'), /^8:14\sPM PT$/u);
  assert.equal(formatMoment(ts, 'date', 'America/New_York'), 'Oct 22, 2026');
  assert.equal(formatMoment(ts, 'date', 'Asia/Kolkata'), 'Oct 23, 2026');
  assert.equal(formatMoment(ts, 'date', 'America/Los_Angeles'), shortDate(todayPT(new Date(ts))));
});
