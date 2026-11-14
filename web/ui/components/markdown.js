// The guides' Markdown (requirements S12.7.4): headings, paragraphs, lists, tables, code, quotes
// (shown as notes), images, links, bold and italic. Everything is built as elements from text,
// so raw HTML in a guide is shown as text, never parsed.
import { h } from 'preact';
import { slug } from '../kit/format.js';
import { Term } from './term.js';

/** @typedef {Map<string, import('./term.js').Entry>} Glossary */
/**
 * @typedef {{ terms: Glossary, forms: Glossary, words: Map<string, string>, re: RegExp,
 *   seen: Set<string> }} Marking  `words`: how a guide names each form ("1099-DIV")
 */

/**
 * The guides' glossary (S12.7.7): each "## AGI: Adjusted Gross Income" heading of
 * guides/terms.md, the paragraph under it as the explanation, and a last line that is only a
 * link, "[IRS Publication 590-A](https://…)", as the official document. guides/forms.md lists the
 * IRS forms the same way, "## Form 1099-DIV: Dividends and Distributions" (S12.7.8).
 * @param {string} md
 * @returns {Glossary}
 */
export function glossary(md) {
  const out = new Map();
  for (const part of md.replace(/\r/g, '').split(/^## /m).slice(1)) {
    const [head, ...body] = part.trim().split('\n');
    const m = head.match(/^([A-Z][A-Z0-9]*|(?:Form|Schedule) [0-9A-Z-]+): (.+)$/);
    if (!m) continue;
    const link = body.at(-1)?.match(/^\[([^\]]+)\]\((https:\/\/[^)\s]+)\)$/);
    if (link) body.pop();
    out.set(m[1], {
      title: m[2].trim(),
      text: body.join(' ').replace(/\s+/g, ' ').trim(),
      source: link ? { label: link[1], href: link[2] } : undefined,
    });
  }
  return out;
}

/**
 * How a guide names a form: "Form 8949" and "Schedule D" in full, and "1099-DIV" or "W-2" alone
 * too, since they can be nothing else. A bare number is never taken for a form.
 * @param {string} name
 */
function wordsFor(name) {
  const bare = name.replace(/^Form /, '');
  return bare !== name && /[A-Z]/.test(bare) ? [name, bare] : [name];
}

/**
 * Each use of a glossary term, plural or not, and of a form, as a Term: a section's first
 * underlined, later ones quiet (S12.7.7, S12.7.8).
 * @param {string} text
 * @param {Marking | null} marking
 * @returns {any[]}
 */
function mark(text, marking) {
  if (!marking) return [text];
  const out = [];
  let last = 0;
  for (const m of text.matchAll(marking.re)) {
    if (m.index === undefined) continue;
    const key = /** @type {string} */ (m[1] ? marking.words.get(m[1]) : m[2]);
    const quiet = marking.seen.has(key);
    marking.seen.add(key);
    if (m.index > last) out.push(text.slice(last, m.index));
    const entry = /** @type {import('./term.js').Entry} */ (
      (m[1] ? marking.forms : marking.terms).get(key)
    );
    out.push(h(Term, { ...entry, term: key, word: m[0], quiet }));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/**
 * Inline spans: `code`, **bold**, *italic* or _italic_, [links](url) and ![images](src).
 * @param {string} text
 * @param {(src: string) => string} resolve
 * @param {Marking | null} marking  the terms and forms to mark, none inside code or a link
 * @returns {any[]}
 */
function inline(text, resolve, marking) {
  const out = [];
  const re =
    /(`[^`]+`)|(!\[[^\]]*\]\([^)]+\))|(\[[^\]]+\]\([^)]+\))|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\b_[^_]+_\b)/;
  let rest = text;
  while (rest) {
    const m = rest.match(re);
    if (!m || m.index === undefined) {
      out.push(...mark(rest, marking));
      break;
    }
    if (m.index) out.push(...mark(rest.slice(0, m.index), marking));
    const t = m[0];
    if (t.startsWith('`')) out.push(h('code', null, t.slice(1, -1)));
    else if (t.startsWith('![')) {
      const [, alt, src] = /** @type {RegExpMatchArray} */ (t.match(/!\[([^\]]*)\]\(([^)]+)\)/));
      out.push(h('img', { src: resolve(src), alt, loading: 'lazy' }));
    } else if (t.startsWith('[')) {
      const [, label, href] = /** @type {RegExpMatchArray} */ (t.match(/\[([^\]]+)\]\(([^)]+)\)/));
      const external = /^https?:/.test(href);
      out.push(h('a', {
        href,
        target: external ? '_blank' : undefined,
        rel: external ? 'noopener noreferrer' : undefined,
      }, inline(label, resolve, null)));
    } else if (t.startsWith('**')) {
      out.push(h('b', null, inline(t.slice(2, -2), resolve, marking)));
    } else out.push(h('i', null, inline(t.slice(1, -1), resolve, marking)));
    rest = rest.slice(m.index + t.length);
  }
  return out;
}

/**
 * A heading's anchor: an id it lists ("## Lot method {#lots}") or its text's slug (S12.7.3).
 * @param {string} text
 */
export function anchorOf(text) {
  const m = text.match(/\{#([a-z0-9-]+)\}\s*$/);
  return m ? { text: text.slice(0, m.index).trim(), id: m[1] } : { text, id: slug(text) };
}

/**
 * @param {string} md
 * @param {(src: string) => string} resolve  where an image's path points
 * @param {Glossary} [terms]  the acronyms to explain on hover and focus (S12.7.7)
 * @param {Glossary} [forms]  the IRS forms, shown as the terms are (S12.7.8)
 */
export function render(md, resolve = (s) => s, terms = new Map(), forms = new Map()) {
  const lines = md.replace(/\r/g, '').split('\n');
  const out = [];
  let i = 0;
  let key = 0;
  /** @type {Map<string, string>} */
  const words = new Map([...forms.keys()].flatMap((f) => wordsFor(f).map((w) => [w, f])));
  // Each list longest first; '(?!)' matches nothing.
  const any = (/** @type {string[]} */ xs) =>
    xs.length ? xs.sort((a, b) => b.length - a.length).join('|') : '(?!)';
  // Group 1 a form, group 2 a term.
  const re = new RegExp(
    `(?<![\\w-])(${any([...words.keys()])})(?![\\w-])|\\b(${any([...terms.keys()])})s?\\b`,
    'g',
  );
  /** @type {Marking | null} */
  const marking = terms.size || forms.size ? { terms, forms, words, re, seen: new Set() } : null;
  const span = (/** @type {string} */ text) => inline(text, resolve, marking);
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.startsWith('```')) {
      const code = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++]);
      i++;
      out.push(h('pre', { key: key++ }, h('code', null, code.join('\n'))));
      continue;
    }
    const head = line.match(/^(#{1,3})\s+(.*)$/);
    if (head) {
      const level = head[1].length;
      const { text, id } = anchorOf(head[2]);
      marking?.seen.clear();
      out.push(h('h' + level, {
        key: key++,
        id: level === 2 ? 'h-' + id : undefined,
        'data-anchor': level === 2 ? id : undefined,
      }, span(text)));
      i++;
      continue;
    }
    if (line.startsWith('>')) {
      const quote = [];
      while (i < lines.length && lines[i].startsWith('>')) {
        quote.push(lines[i++].replace(/^>\s?/, ''));
      }
      out.push(h('blockquote', { key: key++ }, span(quote.join(' '))));
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        let item = lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, '');
        while (
          i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*]|\d+\.)\s/.test(lines[i])
        ) {
          item += ' ' + lines[i++].trim();
        }
        items.push(h('li', null, span(item)));
      }
      out.push(h(ordered ? 'ol' : 'ul', { key: key++ }, items));
      continue;
    }
    if (line.startsWith('|')) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith('|')) rows.push(lines[i++]);
      const cells = (/** @type {string} */ r) => r.slice(1, -1).split('|').map((c) => c.trim());
      const [first, sep, ...body] = rows;
      const hasHead = sep && /^\|[\s:|-]+\|$/.test(sep);
      out.push(h('table', { key: key++ }, [
        hasHead
          ? h(
            'thead',
            null,
            h('tr', null, cells(first).map((c) => h('th', null, span(c)))),
          )
          : null,
        h(
          'tbody',
          null,
          (hasHead ? body : rows).map((r) =>
            h('tr', null, cells(r).map((c) => h('td', null, span(c))))
          ),
        ),
      ]));
      continue;
    }
    const para = [line];
    i++;
    while (
      i < lines.length && lines[i].trim() && !/^(#|>|```|\||\s*([-*]|\d+\.)\s)/.test(lines[i])
    ) {
      para.push(lines[i++]);
    }
    out.push(h('p', { key: key++ }, span(para.join(' '))));
  }
  return out;
}

/**
 * Put the parts a guide names into it: a line "{{part NAME}}" becomes guides/NAME.md, and
 * "{{account-type SECTION}}" the section of guides/account-TYPE.md that starts "@@ SECTION".
 * @param {string} md
 * @param {(name: string) => Promise<string>} load
 * @param {Record<string, string>} vars
 */
export async function assemble(md, load, vars = {}) {
  const lines = md.split('\n');
  const out = [];
  for (const line of lines) {
    const part = line.match(/^\{\{part ([a-z0-9-]+)\}\}$/);
    const typed = line.match(/^\{\{account-type ([a-z0-9-]+)\}\}$/);
    if (part) out.push(await load(part[1]).catch(() => ''));
    else if (typed) {
      if (!vars.type) continue;
      const text = await load('account-' + vars.type).catch(() => '');
      const sections = text.split(/^@@ /m);
      const found = sections.find((s) => s.startsWith(typed[1] + '\n'));
      if (found) out.push(found.slice(typed[1].length + 1));
    } else out.push(line);
  }
  return out.join('\n');
}
