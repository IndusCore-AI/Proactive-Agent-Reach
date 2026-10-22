import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';

import { UNLOCK_MAX_AGE, passphraseMatches, signUnlock, verifyUnlock } from './unlock.ts';

const SECRET = 'test-secret-that-is-at-least-32-characters-long';
const NOW = 1_800_000_000;

test('a cookie we signed verifies until it expires', () => {
  const value = signUnlock(NOW + UNLOCK_MAX_AGE, SECRET);
  assert.equal(verifyUnlock(value, SECRET, NOW), true);
  assert.equal(verifyUnlock(value, SECRET, NOW + UNLOCK_MAX_AGE - 1), true);
  assert.equal(verifyUnlock(value, SECRET, NOW + UNLOCK_MAX_AGE), false);
});

test('forged, tampered, foreign and malformed cookies never verify', () => {
  const exp = NOW + 3600;
  const good = signUnlock(exp, SECRET);
  const sig = good.split('.')[1];
  assert.equal(verifyUnlock(`${exp + 1}.${sig}`, SECRET, NOW), false); // extended expiry
  assert.equal(verifyUnlock(`${exp}.${'0'.repeat(64)}`, SECRET, NOW), false);
  assert.equal(verifyUnlock(signUnlock(exp, `${SECRET}-other`), SECRET, NOW), false);
  assert.equal(verifyUnlock(`${exp}.${sig.toUpperCase()}`, SECRET, NOW), false);
  assert.equal(verifyUnlock(`${exp}`, SECRET, NOW), false);
  assert.equal(verifyUnlock('', SECRET, NOW), false);
  assert.equal(verifyUnlock(undefined, SECRET, NOW), false);
  assert.equal(verifyUnlock('1;2', SECRET, NOW), false);
  // Signed with the right secret but claiming to live longer than we ever issue.
  assert.equal(verifyUnlock(signUnlock(NOW + UNLOCK_MAX_AGE * 12, SECRET), SECRET, NOW), false);
});

test('no secret, or a short one, never unlocks', () => {
  const exp = NOW + 3600;
  assert.equal(verifyUnlock(signUnlock(exp, ''), '', NOW), false);
  assert.equal(verifyUnlock(signUnlock(exp, 'short'), 'short', NOW), false);
  assert.equal(verifyUnlock(signUnlock(exp, SECRET), undefined, NOW), false);
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
