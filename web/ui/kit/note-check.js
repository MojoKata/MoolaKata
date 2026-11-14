// Whether a note's document is one a note may hold (requirements S12.18.15), by the table in
// note-spec.json that the editor builds its schema from and the server checks against: each
// kind of block and what it may hold, the marks, the attributes and the limits. Nothing here
// knows the editor; the same rules are the server's.
import SPEC from './note-spec.json' with { type: 'json' };
import { isHref, isPage } from './note-links.js';

export { SPEC };

/** @typedef {{ type: string, content?: Doc[], attrs?: Record<string, any>,
 *   marks?: { type: string, attrs?: Record<string, any> }[], text?: string }} Doc */

/** @typedef {{ names: Set<string>, min: number, max: number }} Term */

const KEYS = new Set(['type', 'content', 'attrs', 'marks', 'text']);

/**
 * A node's content rule read into its terms, in order: which kinds each takes, how few and how
 * many. The rules use only `a`, `a*`, `a+`, `a?` and `(a | b)` with those after it.
 * @param {string} rule
 * @returns {Term[]}
 */
export function terms(rule) {
  /** @type {Term[]} */
  const out = [];
  for (const m of rule.matchAll(/(\(([^)]*)\)|([a-z]+))([*+?]?)/g)) {
    const words = (m[2] ?? m[3]).split('|').map((w) => w.trim()).filter(Boolean);
    const names = new Set(words.flatMap((w) => kinds(w)));
    const q = m[4];
    out.push({
      names,
      min: q === '*' || q === '?' ? 0 : 1,
      max: q === '*' || q === '+' ? Infinity : 1,
    });
  }
  return out;
}

/** The kinds a word of a rule names: a kind itself, or every kind in that group. @param {string} w */
function kinds(w) {
  const nodes = /** @type {Record<string, any>} */ (SPEC.nodes);
  if (nodes[w]) return [w];
  return Object.keys(nodes).filter((k) => nodes[k].group === w);
}

/**
 * Whether a list of kinds follows a rule. Its terms never overlap where it matters, so each
 * takes all it can in turn.
 * @param {string[]} seen @param {Term[]} rule
 */
export function follows(seen, rule) {
  let i = 0;
  for (const t of rule) {
    let n = 0;
    while (i < seen.length && n < t.max && t.names.has(seen[i])) {
      i++;
      n++;
    }
    if (n < t.min) return false;
  }
  return i === seen.length;
}

const RULES = new Map(
  Object.entries(/** @type {Record<string, any>} */ (SPEC.nodes))
    .filter(([, s]) => s.content)
    .map(([k, s]) => [k, terms(s.content)]),
);

/**
 * A note checked: its characters, and each thing wrong with it, in words.
 * @param {unknown} doc
 * @returns {{ chars: number, problems: string[] }}
 */
export function checkNote(doc) {
  /** @type {string[]} */
  const problems = [];
  let chars = 0;
  const nodes = /** @type {Record<string, any>} */ (SPEC.nodes);
  const marks = /** @type {Record<string, any>} */ (SPEC.marks);
  /** @param {any} n @param {string} at @param {string} allowed @param {number} depth */
  const walk = (n, at, allowed, depth) => {
    if (!n || typeof n !== 'object' || Array.isArray(n)) return problems.push(`${at}: not a node`);
    const extra = Object.keys(n).filter((k) => !KEYS.has(k));
    if (extra.length) problems.push(`${at}: ${extra.join(', ')} not known`);
    const spec = nodes[n.type];
    if (!spec || n.type === 'doc') {
      return problems.push(`${at}: “${n.type}” is not a kind a note holds`);
    }
    const here = `${at}.${n.type}`;
    checkAttrs(n, spec, here, problems);
    if (n.type === 'text') {
      if (typeof n.text !== 'string' || !n.text) problems.push(`${here}: no text`);
      else chars += [...n.text].length;
    } else if (n.text !== undefined) problems.push(`${here}: text where none belongs`);
    if (n.marks !== undefined) checkMarks(n.marks, allowed, here, marks, problems);
    const list = n.type === 'bullets' || n.type === 'numbers';
    const deep = depth + (list ? 1 : 0);
    if (list && deep > SPEC.limits.listDepth) {
      problems.push(`Lists go ${SPEC.limits.listDepth} deep at most.`);
    }
    if (spec.content) children(n, here, spec, deep);
    else if (n.content !== undefined) problems.push(`${here}: holds nothing`);
  };
  /** @param {any} n @param {string} at @param {any} spec @param {number} depth */
  const children = (n, at, spec, depth) => {
    const content = n.content ?? [];
    if (!Array.isArray(content)) return problems.push(`${at}: its content is not a list`);
    const rule = /** @type {Term[]} */ (RULES.get(n.type));
    const seen = content.map((/** @type {any} */ c) => c?.type);
    if (!follows(seen, rule)) problems.push(`${at}: holds ${seen.join(', ') || 'nothing'}`);
    content.forEach((/** @type {any} */ c, /** @type {number} */ i) =>
      walk(c, `${at}[${i}]`, spec.marks ?? '', depth)
    );
  };
  if (!doc || typeof doc !== 'object' || /** @type {any} */ (doc).type !== 'doc') {
    return { chars, problems: ['Not a note.'] };
  }
  const d = /** @type {any} */ (doc);
  const extra = Object.keys(d).filter((k) => k !== 'type' && k !== 'content');
  if (extra.length) problems.push(`doc: ${extra.join(', ')} not known`);
  children(d, 'doc', nodes.doc, 0);
  if (chars > SPEC.limits.chars) {
    problems.unshift(
      `At most ${SPEC.limits.chars.toLocaleString('en-US')} characters (this has ${
        chars.toLocaleString('en-US')
      }).`,
    );
  }
  const bytes = new TextEncoder().encode(JSON.stringify(doc)).length;
  if (bytes > SPEC.limits.bytes) problems.push('Too much formatting for its length.');
  return { chars, problems };
}

/**
 * A node's attributes: only those its kind has, each one of its values.
 * @param {any} n @param {any} spec @param {string} at @param {string[]} problems
 */
function checkAttrs(n, spec, at, problems) {
  if (n.attrs === undefined) {
    if (spec.attrs) problems.push(`${at}: no ${Object.keys(spec.attrs).join(', ')}`);
    return;
  }
  if (!n.attrs || typeof n.attrs !== 'object' || !spec.attrs) {
    return problems.push(`${at}: attributes where none belong`);
  }
  for (const [k, v] of Object.entries(n.attrs)) {
    if (!(k in spec.attrs)) problems.push(`${at}: ${k} not known`);
    else if (!spec.attrs[k].includes(v)) problems.push(`${at}: ${k} ${JSON.stringify(v)}`);
  }
  for (const k of Object.keys(spec.attrs)) if (!(k in n.attrs)) problems.push(`${at}: no ${k}`);
}

/**
 * A text's marks: each known, allowed where it is, once; a link to a page or an address, not
 * both.
 * @param {any} list @param {string} allowed  `_` any, `` none
 * @param {string} at @param {Record<string, any>} marks @param {string[]} problems
 */
function checkMarks(list, allowed, at, marks, problems) {
  if (!Array.isArray(list)) return problems.push(`${at}: its marks are not a list`);
  if (list.length && allowed !== '_') return problems.push(`${at}: no marks here`);
  const seen = new Set();
  for (const m of list) {
    if (!m || typeof m !== 'object' || !marks[m.type]) {
      problems.push(`${at}: mark “${m?.type}” not known`);
      continue;
    }
    if (seen.has(m.type)) problems.push(`${at}: ${m.type} twice`);
    seen.add(m.type);
    const extra = Object.keys(m).filter((k) => k !== 'type' && k !== 'attrs');
    if (extra.length) problems.push(`${at}: ${extra.join(', ')} not known`);
    if (m.type !== 'link') {
      if (m.attrs !== undefined) problems.push(`${at}: ${m.type} takes no attributes`);
      continue;
    }
    const a = m.attrs ?? {};
    const keys = Object.keys(a);
    const one = keys.length === 1 && (keys[0] === 'href' || keys[0] === 'page');
    if (!one) problems.push(`${at}: a link goes to an address or a page`);
    else if (keys[0] === 'href' && !isHref(a.href)) {
      problems.push(`${at}: not an http or https address`);
    } else if (keys[0] === 'page' && !isPage(a.page)) {
      problems.push(`${at}: not a page of MoolaKata`);
    }
  }
}

/**
 * A note as plain text, for search, exports and summaries: a line a block, a list's items each
 * on its own line.
 * @param {Doc | null | undefined} doc
 */
export function plainText(doc) {
  /** @type {string[]} */
  const lines = [];
  /** @param {Doc} n @returns {string} */
  const inline = (n) =>
    (n.content ?? []).map((c) => (c.type === 'break' ? '\n' : c.text ?? '')).join('');
  /** @param {Doc} n */
  const block = (n) => {
    if (n.type === 'paragraph' || n.type === 'heading' || n.type === 'pre') lines.push(inline(n));
    else for (const c of n.content ?? []) block(c);
  };
  if (doc?.type === 'doc') { for (const c of doc.content ?? []) block(c); }
  return lines.join('\n');
}

/** Whether a note holds nothing worth keeping: no text at all. @param {Doc | null | undefined} doc */
export function isEmpty(doc) {
  return !plainText(doc).trim();
}
