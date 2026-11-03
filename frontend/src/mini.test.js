import assert from 'node:assert/strict';
import { test } from 'node:test';
import { blocks, inline } from './mini.js';

test('bold runs are split out and nothing else is interpreted', () => {
  assert.deepEqual(inline('a **b** c'), [{ t: 'a ' }, { t: 'b', b: true }, { t: ' c' }]);
  assert.deepEqual(inline('<img src=x onerror=alert(1)>'), [{ t: '<img src=x onerror=alert(1)>' }]);
  assert.deepEqual(inline('a ** b'), [{ t: 'a ** b' }]);
});

test('headings, paragraphs and bullets', () => {
  const b = blocks('**What happened**\nErrors went up.\nIt was slow.\n\n**Next**\n- check logs\n* look at **db**');
  assert.deepEqual(b.map((x) => x.type), ['h', 'p', 'h', 'li', 'li']);
  assert.equal(b[1].parts.map((p) => p.t).join(''), 'Errors went up. It was slow.');
  assert.equal(b[4].parts[1].b, true);
});

test('empty and missing text give no blocks', () => {
  assert.deepEqual(blocks(''), []);
  assert.deepEqual(blocks(null), []);
});
