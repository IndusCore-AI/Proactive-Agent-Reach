import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ingestPathAllowed } from './ingestPaths.ts';

const RUN = '0b6c3c9e-8f0e-4f7a-9a51-3f3b5f1c2d4e';

test('the daily run paths stay allowed', () => {
  assert.equal(ingestPathAllowed('POST', ['runs']), true);
  assert.equal(ingestPathAllowed('POST', ['runs', RUN, 'items']), true);
  assert.equal(ingestPathAllowed('POST', ['runs', RUN, 'finish']), true);
  assert.equal(ingestPathAllowed('GET', ['runs', RUN]), true);
  assert.equal(ingestPathAllowed('GET', ['editions', '2026-01-01']), true);
});

test('mover paths are allowed with the right method only', () => {
  assert.equal(ingestPathAllowed('GET', ['movers']), true);
  assert.equal(ingestPathAllowed('POST', ['movers']), true);
  assert.equal(ingestPathAllowed('POST', ['movers', 'example-robotics', 'link']), true);
  assert.equal(ingestPathAllowed('POST', ['movers', 'example-robotics', 'archive']), true);
  assert.equal(ingestPathAllowed('GET', ['movers', 'example-robotics', 'archive']), false);
  assert.equal(ingestPathAllowed('POST', ['movers', 'example-robotics', 'delete']), false);
  assert.equal(ingestPathAllowed('POST', ['movers', '-bad', 'link']), false);
});

test('anything else is refused', () => {
  assert.equal(ingestPathAllowed('GET', ['private', 'movers']), false);
  assert.equal(ingestPathAllowed('POST', ['runs', 'not-a-uuid', 'items']), false);
  assert.equal(ingestPathAllowed('GET', ['editions', '2026-1-1']), false);
  assert.equal(ingestPathAllowed('POST', []), false);
});
