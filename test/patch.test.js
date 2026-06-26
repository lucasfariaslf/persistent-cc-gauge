'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { planPatch, planRevert, VIS_PATCHED, PIE_MARK, FOOTER_MARK } = require('../src/patch');

// Build a representative bundle slice from a given identifier set, so we can
// prove the structural transforms are version-independent. `ids` mirrors what
// different minified releases produce (pie fn, bucket tables, footer init call,
// useEffect alias).
function bundle(ids) {
  const pie =
    'function ' + ids.fn + '({percentage:e,className:t}){let i=' + ids.b1 + '(e),n=' + ids.b2 + '[i];' +
    'return ' + ids.E + '("svg",{width:"20",height:"20",viewBox:"0 0 20 20",fill:"none",' +
    'xmlns:"http://www.w3.org/2000/svg",className:t,style:{display:"block"},children:[n&&' + ids.B + '("path",{d:n,' +
    'stroke:"currentColor",strokeOpacity:"0.15",strokeWidth:"1.5",strokeLinecap:"round"}),' + ids.B + '("path",{d:' + ids.b3 + '[i],' +
    'stroke:"var(--app-claude-clay-button-orange)",strokeWidth:"1.5",strokeLinecap:"round"})]})}';
  const peAlias = ids.pe + '=function(e,t){return cf.current.useEffect(e,t)}';
  const footer = 'onTerminalCollaborator:h}){' + ids.call + '();let p=null;if(e.busy.value)p=1;return 0}';
  const guard = 'if(t===0)return null;if(c>=50)return null';
  // arbitrary surrounding minified noise
  return 'AAA;' + peAlias + ';BBB;' + pie + ';CCC;' + guard + ';DDD;' + footer + ';EEE';
}

const V193 = { fn: 'wXe', b1: 'K9t', b2: 'q9t', b3: '$9t', E: 'E', B: 'b', call: 'Nn', pe: 'pe' };
const V187 = { fn: 'bXe', b1: 'z9t', b2: 'W9t', b3: 'V9t', E: 'E', B: 'b', call: 'zn', pe: 'tp' };

for (const [label, ids] of [['v193 ids', V193], ['v187 ids', V187]]) {
  test(label + ': applies all three transforms', () => {
    const src = bundle(ids);
    const r = planPatch(src);
    assert.equal(r.status, 'patched');
    assert.deepEqual(r.applied.sort(), ['continuous-pie', 'prefetch-context', 'visibility-guard']);
    assert.ok(r.content.includes(VIS_PATCHED));
    assert.ok(r.content.includes(PIE_MARK));
    assert.ok(r.content.includes(FOOTER_MARK));
  });

  test(label + ': patch is idempotent', () => {
    const once = planPatch(bundle(ids)).content;
    const again = planPatch(once);
    assert.equal(again.status, 'already');
    assert.equal(again.content, once);
  });

  test(label + ': revert restores the exact original', () => {
    const src = bundle(ids);
    const patched = planPatch(src).content;
    assert.notEqual(patched, src);
    const r = planRevert(patched);
    assert.equal(r.status, 'reverted');
    assert.equal(r.content, src); // byte-exact round trip
  });

  test(label + ': revert is a no-op on a clean bundle', () => {
    assert.equal(planRevert(bundle(ids)).status, 'not-patched');
  });
}

test('missing visibility guard -> not-found, nothing changed', () => {
  const src = bundle(V193).replace('if(t===0)return null;if(c>=50)return null', 'xx');
  const r = planPatch(src);
  assert.equal(r.status, 'not-found');
  assert.equal(r.content, src);
});

test('duplicate visibility guard -> ambiguous, nothing changed', () => {
  const g = 'if(t===0)return null;if(c>=50)return null';
  const src = bundle(V193) + ';' + g;
  const r = planPatch(src);
  assert.equal(r.status, 'ambiguous');
  assert.equal(r.content, src);
});

test('pie absent -> still patches guard, soft-skips pie', () => {
  // break the pie find anchor (its destructured signature) but keep guard + footer
  const src = bundle(V193).replace('{percentage:e,className:t}', '{percentage:e}');
  const r = planPatch(src);
  assert.equal(r.status, 'patched');
  assert.ok(r.applied.includes('visibility-guard'));
  assert.ok(r.skipped.includes('continuous-pie'));
});

test('useEffect alias not unique -> soft-skips prefetch, still patches the rest', () => {
  // add a second pe alias so PE_FIND count != 1
  const src = bundle(V193) + ';pe=function(e,t){return cf.current.useEffect(e,t)}';
  const r = planPatch(src);
  assert.equal(r.status, 'patched');
  assert.ok(r.applied.includes('visibility-guard'));
  assert.ok(r.applied.includes('continuous-pie'));
  assert.ok(r.skipped.includes('prefetch-context'));
});

test('tampered patched pie body -> revert refuses (corrupt), does not mangle', () => {
  const patched = planPatch(bundle(V193)).content;
  const tampered = patched.replace('col=p<30?"#3fb950"', 'col=p<30?"#000000"');
  const r = planRevert(tampered);
  assert.equal(r.status, 'error');
  assert.match(r.message, /continuous-pie restore-block-corrupt/);
  assert.equal(r.content, tampered);
});

test('legacy plain-marker footer is not double-injected', () => {
  // Simulate a bundle patched by the old script: the footer anchor is followed
  // by a plain /*gauge-always*/ marker, not the b64 marker. planPatch must NOT
  // inject a second prefetch hook.
  const src = bundle(V193).replace(
    'onTerminalCollaborator:h}){Nn();',
    'onTerminalCollaborator:h}){Nn();/*gauge-always*/X(()=>{},[]);'
  );
  const r = planPatch(src);
  assert.ok(r.skipped.includes('prefetch-context'));
  // exactly one prefetch effect remains (the legacy one), none added
  assert.equal((r.content.match(/onTerminalCollaborator:h\}\)\{Nn\(\);/g) || []).length, 1);
  assert.ok(!r.content.includes('getContextUsage'));
});

test('tampered patched pie body -> re-apply refuses (marker corrupt)', () => {
  const patched = planPatch(bundle(V193)).content;
  const tampered = patched.replace('col=p<30?"#3fb950"', 'col=p<30?"#000000"');
  const r = planPatch(tampered);
  assert.equal(r.status, 'error');
  assert.match(r.message, /continuous-pie marker-present-but-block-corrupt/);
});
