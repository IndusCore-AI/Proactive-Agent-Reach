import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';

import { UNLOCK_MAX_AGE, passphraseMatches, safeReturn, signUnlock, verifyUnlock } from './unlock.ts';

const SECRET = 'test-secret-that-is-at-least-32-characters-long';
const NOW = 1_800_000_000;

test('a cookie we signed verifies, as its founder, until it expires', () => {
  const value = signUnlock(NOW + UNLOCK_MAX_AGE, 'michael', SECRET);
  assert.equal(verifyUnlock(value, SECRET, NOW), 'michael');
  assert.equal(verifyUnlock(value, SECRET, NOW + UNLOCK_MAX_AGE - 1), 'michael');
  assert.equal(verifyUnlock(value, SECRET, NOW + UNLOCK_MAX_AGE), null);
  assert.equal(verifyUnlock(signUnlock(NOW + 60, 'pulkit', SECRET), SECRET, NOW), 'pulkit');
});

test('forged, tampered, foreign and malformed cookies never verify', () => {
  const exp = NOW + 3600;
  const good = signUnlock(exp, 'pulkit', SECRET);
  const sig = good.split('.')[2];
  assert.equal(verifyUnlock(`${exp + 1}.pulkit.${sig}`, SECRET, NOW), null); // extended expiry
  assert.equal(verifyUnlock(`${exp}.michael.${sig}`, SECRET, NOW), null);    // someone else's name
  assert.equal(verifyUnlock(`${exp}.stranger.${sig}`, SECRET, NOW), null);   // not a founder
  assert.equal(verifyUnlock(`${exp}.pulkit.${'0'.repeat(64)}`, SECRET, NOW), null);
  assert.equal(verifyUnlock(signUnlock(exp, 'pulkit', `${SECRET}-other`), SECRET, NOW), null);
  assert.equal(verifyUnlock(`${exp}.pulkit.${sig.toUpperCase()}`, SECRET, NOW), null);
  assert.equal(verifyUnlock(`${exp}.${sig}`, SECRET, NOW), null);             // the old, nameless format
  assert.equal(verifyUnlock(`${exp}`, SECRET, NOW), null);
  assert.equal(verifyUnlock('', SECRET, NOW), null);
  assert.equal(verifyUnlock(undefined, SECRET, NOW), null);
  assert.equal(verifyUnlock('1;2', SECRET, NOW), null);
  // Signed with the right secret but claiming to live longer than we ever issue.
  assert.equal(verifyUnlock(signUnlock(NOW + UNLOCK_MAX_AGE * 12, 'pulkit', SECRET), SECRET, NOW), null);
});

test('no secret, or a short one, never unlocks', () => {
  const exp = NOW + 3600;
  assert.equal(verifyUnlock(signUnlock(exp, 'michael', ''), '', NOW), null);
  assert.equal(verifyUnlock(signUnlock(exp, 'michael', 'short'), 'short', NOW), null);
  assert.equal(verifyUnlock(signUnlock(exp, 'michael', SECRET), undefined, NOW), null);
});

test('the passphrase is checked against its sha256', () => {
  const hash = createHash('sha256').update('correct horse battery staple').digest('hex');
  assert.equal(passphraseMatches('correct horse battery staple', hash), true);
  assert.equal(passphraseMatches('correct horse battery staple', hash.toUpperCase()), true);
  assert.equal(passphraseMatches('correct horse battery staple', `${hash}\n`), true);
  assert.equal(passphraseMatches('correct horse battery stapl', hash), false);
  assert.equal(passphraseMatches('', hash), false);
  assert.equal(passphraseMatches('correct horse battery staple', ''), false);
  assert.equal(passphraseMatches('correct horse battery staple', undefined), false);
  assert.equal(passphraseMatches('correct horse battery staple', 'not-hex'), false);
  assert.equal(passphraseMatches('x'.repeat(513), createHash('sha256').update('x'.repeat(513)).digest('hex')), false);
});

test('a form only ever sends the browser back to a movers page', () => {
  assert.equal(safeReturn('/movers'), '/movers');
  assert.equal(safeReturn('/movers?sort=fit&stage=researching'), '/movers?sort=fit&stage=researching');
  assert.equal(safeReturn('/movers/example-co#decide'), '/movers/example-co#decide');
  assert.equal(safeReturn('/movers/updates'), '/movers/updates');
  for (const bad of ['https://evil.example/movers', '//evil.example', '/moversx', '/about', '/movers\\..\\x', '', null, 5]) {
    assert.equal(safeReturn(bad), '/movers', String(bad));
  }
});
