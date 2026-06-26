'use strict';

// Pure string transforms on the Claude Code webview bundle. No file IO here so
// the logic is unit-testable. The extension layer reads the bundle, calls
// planPatch / planRevert, and writes the result.
//
// Three transforms, each leaving a marker so runs are idempotent and revert is
// exact:
//   1) visibility-guard  - exact swap; matches stable code, robust across versions
//   2) continuous-pie     - structural regex; replaces the bucketed pie renderer
//   3) prefetch-context   - structural regex; injects a useEffect on the footer
//
// The two structural transforms capture the minified identifiers (function name,
// JSX helpers, useEffect alias) instead of hardcoding them, so they survive the
// identifier renames that happen on most extension updates. Each embeds the exact
// bytes it replaced (base64url) in its marker, so revert reconstructs the
// original without a sidecar backup.
//
// The marker format is identical to the standalone python patcher this extension
// replaced, so a bundle already patched by that script is recognized here as
// already-patched and is revertible.

const ID = '[A-Za-z_$][\\w$]*'; // a minified JS identifier

// 1) visibility-guard ------------------------------------------------------
const VIS_ORIG = 'if(t===0)return null;if(c>=50)return null';
const VIS_PATCHED = 'if(t<=0||e<=0)return null/*gauge-always*/';

// 2) continuous-pie --------------------------------------------------------
const PIE_MARK = '/*gauge-always:continuous-pie:v1:';
const PIE_FIND = new RegExp(
  'function (?<fn>' + ID + ')\\(\\{percentage:e,className:t\\}\\)\\{' +
  'let i=' + ID + '\\(e\\),n=' + ID + '\\[i\\];' +
  'return (?<E>' + ID + ')\\("svg",\\{width:"20",height:"20",viewBox:"0 0 20 20",' +
  'fill:"none",xmlns:"http://www\\.w3\\.org/2000/svg",className:t,' +
  'style:\\{display:"block"\\},children:\\[n&&(?<B>' + ID + ')\\("path",\\{d:n,' +
  'stroke:"currentColor",strokeOpacity:"0\\.15",strokeWidth:"1\\.5",' +
  'strokeLinecap:"round"\\}\\),\\k<B>\\("path",\\{d:' + ID + '\\[i\\],' +
  'stroke:"var\\(--app-claude-clay-button-orange\\)",strokeWidth:"1\\.5",' +
  'strokeLinecap:"round"\\}\\)\\]\\}\\)\\}',
  'g'
);
const PIE_RESTORE = new RegExp(
  'function ' + ID + '\\(\\{percentage:e,className:t\\}\\)\\{' +
  '/\\*gauge-always:continuous-pie:v1:(?<b64>[A-Za-z0-9_=-]+)\\*/' +
  'let p=Math\\.max\\(0,Math\\.min\\(100,e\\)\\),C=31\\.4159,off=C\\*\\(1-p/100\\),' +
  'col=p<30\\?"#3fb950":p<=50\\?"#d29922":"#f85149";' +
  'return ' + ID + '\\("svg",\\{width:"20",height:"20",viewBox:"0 0 20 20",' +
  'fill:"none",xmlns:"http://www\\.w3\\.org/2000/svg",className:t,' +
  'style:\\{display:"block"\\},children:\\[' + ID + '\\("circle",\\{cx:"10",cy:"10",' +
  'r:"5",stroke:"currentColor",strokeOpacity:"0\\.15",strokeWidth:"1\\.5"\\}\\),' +
  ID + '\\("circle",\\{cx:"10",cy:"10",r:"5",stroke:col,strokeWidth:"1\\.5",' +
  'strokeLinecap:"round",strokeDasharray:C,strokeDashoffset:off,' +
  'transform:"rotate\\(-90 10 10\\)"\\}\\)\\]\\}\\)\\}',
  'g'
);

function buildPie(m) {
  const fn = m.groups.fn, E = m.groups.E, B = m.groups.B;
  const b64 = Buffer.from(m[0], 'utf8').toString('base64url');
  return (
    'function ' + fn + '({percentage:e,className:t}){' +
    '/*gauge-always:continuous-pie:v1:' + b64 + '*/' +
    'let p=Math.max(0,Math.min(100,e)),C=31.4159,off=C*(1-p/100),' +
    'col=p<30?"#3fb950":p<=50?"#d29922":"#f85149";' +
    'return ' + E + '("svg",{width:"20",height:"20",viewBox:"0 0 20 20",' +
    'fill:"none",xmlns:"http://www.w3.org/2000/svg",className:t,' +
    'style:{display:"block"},children:[' + B + '("circle",{cx:"10",cy:"10",' +
    'r:"5",stroke:"currentColor",strokeOpacity:"0.15",strokeWidth:"1.5"}),' +
    B + '("circle",{cx:"10",cy:"10",r:"5",stroke:col,strokeWidth:"1.5",' +
    'strokeLinecap:"round",strokeDasharray:C,strokeDashoffset:off,' +
    'transform:"rotate(-90 10 10)"})]})}'
  );
}

// 3) prefetch-context ------------------------------------------------------
const FOOTER_MARK = '/*gauge-always:prefetch-context:v1:';
// The negative lookahead refuses a footer that is already followed by any
// gauge marker, so a bundle patched by an older version of this tool (which used
// a plain /*gauge-always*/ marker here) is not injected a second time.
const FOOTER_FIND = new RegExp('onTerminalCollaborator:h\\}\\)\\{(?<call>' + ID + ')\\(\\);(?!/\\*gauge-always)', 'g');
const PE_FIND = new RegExp('(?<pe>' + ID + ')=function\\(e,t\\)\\{return ' + ID + '(?:\\.' + ID + ')*\\.current\\.useEffect\\(e,t\\)\\}', 'g');
const FOOTER_RESTORE = new RegExp(
  'onTerminalCollaborator:h\\}\\)\\{' + ID + '\\(\\);' +
  '/\\*gauge-always:prefetch-context:v1:(?<b64>[A-Za-z0-9_=-]+)\\*/' +
  ID + '\\(\\(\\)=>\\{try\\{e\\.getContextUsage\\?\\.\\(\\)\\.then\\(a=>\\{' +
  'let u=a&&a\\.usage;if\\(!u\\)return;' +
  'e\\.usageData\\.value=\\{\\.\\.\\.e\\.usageData\\.value,' +
  'totalTokens:u\\.totalTokens,contextWindow:u\\.rawMaxTokens,maxOutputTokens:0\\};' +
  '\\}\\)\\.catch\\(\\(\\)=>\\{\\}\\);\\}catch\\{\\}\\},\\[\\]\\);',
  'g'
);

// Thrown by buildFooter when its preconditions are not met; the caller turns it
// into a soft skip (the robust visibility guard still applies).
class PrecondError extends Error {}

function buildFooter(m, source) {
  const pes = [...source.matchAll(PE_FIND)];
  if (pes.length !== 1) throw new PrecondError('useEffect-alias-count-' + pes.length);
  const pe = pes[0].groups.pe;
  const call = m.groups.call;
  const b64 = Buffer.from(m[0], 'utf8').toString('base64url');
  return (
    'onTerminalCollaborator:h}){' + call + '();' +
    '/*gauge-always:prefetch-context:v1:' + b64 + '*/' +
    pe + '(()=>{try{e.getContextUsage?.().then(a=>{' +
    'let u=a&&a.usage;if(!u)return;' +
    'e.usageData.value={...e.usageData.value,' +
    'totalTokens:u.totalTokens,contextWindow:u.rawMaxTokens,maxOutputTokens:0};' +
    '}).catch(()=>{});}catch{}},[]);'
  );
}

const REGEX_TRANSFORMS = [
  { name: 'continuous-pie', find: PIE_FIND, restore: PIE_RESTORE, mark: PIE_MARK, build: buildPie },
  { name: 'prefetch-context', find: FOOTER_FIND, restore: FOOTER_RESTORE, mark: FOOTER_MARK, build: buildFooter },
];

function countOccurrences(haystack, needle) {
  let n = 0, i = 0;
  while ((i = haystack.indexOf(needle, i)) !== -1) { n++; i += needle.length; }
  return n;
}

// Apply one regex transform. Returns { content, status } where status is one of:
// applied | already | skip0 | ('skipN', n) | ('precond', msg) | ('error', msg).
function applyRegex(t, source) {
  const mcount = countOccurrences(source, t.mark);
  if (mcount >= 1) {
    if ([...source.matchAll(t.restore)].length !== mcount) {
      return { content: source, status: ['error', t.name + ' marker-present-but-block-corrupt'] };
    }
    return { content: source, status: 'already' };
  }
  const matches = [...source.matchAll(t.find)];
  if (matches.length === 0) return { content: source, status: 'skip0' };
  if (matches.length > 1) return { content: source, status: ['skipN', matches.length] };
  const m = matches[0];
  let patched;
  try {
    patched = t.build(m, source);
  } catch (err) {
    if (err instanceof PrecondError) return { content: source, status: ['precond', err.message] };
    throw err;
  }
  const cand = source.slice(0, m.index) + patched + source.slice(m.index + m[0].length);
  if (countOccurrences(cand, t.mark) !== 1) {
    return { content: source, status: ['error', t.name + ' postcond-marker'] };
  }
  if ([...cand.matchAll(t.restore)].length !== 1) {
    return { content: source, status: ['error', t.name + ' postcond-restore'] };
  }
  return { content: cand, status: 'applied' };
}

// planPatch: apply all three transforms. Returns:
//   { status, content, applied: [...], skipped: [...], message }
//   status: patched | already | not-found | ambiguous | error
function planPatch(source) {
  let content = source;
  const applied = [];
  const skipped = [];

  // visibility-guard (required, exact).
  if (content.includes(VIS_PATCHED)) {
    // already
  } else {
    const c = countOccurrences(content, VIS_ORIG);
    if (c === 0) return { status: 'not-found', content: source, applied: [], skipped: [], message: 'visibility-guard not found (bundle changed)' };
    if (c > 1) return { status: 'ambiguous', content: source, applied: [], skipped: [], message: 'visibility-guard matched ' + c + ' sites' };
    content = content.replace(VIS_ORIG, VIS_PATCHED);
    applied.push('visibility-guard');
  }

  // optional structural transforms.
  for (const t of REGEX_TRANSFORMS) {
    const r = applyRegex(t, content);
    const st = r.status;
    if (st === 'applied') { content = r.content; applied.push(t.name); }
    else if (st === 'already') { /* nothing */ }
    else if (Array.isArray(st) && st[0] === 'error') {
      return { status: 'error', content: source, applied: [], skipped: [], message: st[1] };
    } else {
      // skip0 / skipN / precond -> soft skip; the robust guard still applies.
      skipped.push(t.name);
    }
  }

  if (applied.length === 0) {
    return { status: 'already', content: source, applied, skipped, message: skipped.length ? 'already; skipped ' + skipped.join(',') : 'already' };
  }
  return { status: 'patched', content, applied, skipped, message: 'patched ' + applied.join(',') + (skipped.length ? '; skipped ' + skipped.join(',') : '') };
}

// planRevert: reverse all transforms. Returns { status, content, reverted, message }
//   status: reverted | not-patched | error
function planRevert(source) {
  let content = source;
  const reverted = [];

  if (content.includes(VIS_PATCHED)) {
    content = content.replace(VIS_PATCHED, VIS_ORIG);
    reverted.push('visibility-guard');
  }

  for (const t of REGEX_TRANSFORMS) {
    const mcount = countOccurrences(content, t.mark);
    if (mcount === 0) continue;
    const matches = [...content.matchAll(t.restore)];
    if (matches.length !== mcount) {
      return { status: 'error', content: source, reverted: [], message: t.name + ' restore-block-corrupt' };
    }
    // Replace from the end so earlier indices stay valid.
    for (let i = matches.length - 1; i >= 0; i--) {
      const m = matches[i];
      let orig;
      try {
        orig = Buffer.from(m.groups.b64, 'base64url').toString('utf8');
      } catch {
        return { status: 'error', content: source, reverted: [], message: t.name + ' bad-b64' };
      }
      // Strict full match (exec + length, not `$`, which can match before a
      // trailing newline): the decoded original must be exactly what find matches.
      const fullRe = new RegExp('^(?:' + t.find.source + ')');
      const fm = fullRe.exec(orig);
      if (!fm || fm[0].length !== orig.length) {
        return { status: 'error', content: source, reverted: [], message: t.name + ' restore-sanity' };
      }
      content = content.slice(0, m.index) + orig + content.slice(m.index + m[0].length);
    }
    reverted.push(t.name);
  }

  if (reverted.length === 0) return { status: 'not-patched', content: source, reverted, message: 'not patched' };
  return { status: 'reverted', content, reverted, message: 'reverted ' + reverted.join(',') };
}

module.exports = {
  planPatch,
  planRevert,
  VIS_ORIG,
  VIS_PATCHED,
  PIE_MARK,
  FOOTER_MARK,
  PIE_FIND,
  FOOTER_FIND,
};
