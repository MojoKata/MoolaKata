// A note read (requirements S12.18.15): its document drawn as the page's own elements, never
// as markup, with no editor loaded. A link to an address opens in a new tab; a link to a page of
// MoolaKata opens in place, through `pages`, or reads as text where that page can't be shown.
import { html } from './html.js';

/**
 * How a page of MoolaKata named in a note is shown here: where it opens, what its tooltip
 * says, and whether it is out of reach (a linked household's window without that screen, say).
 * @typedef {{ href: string, tip: string, off?: boolean, why?: string }} PageLink
 * @typedef {(page: string) => PageLink} Pages
 */

/**
 * The heading levels a screen gives a note: its first (`top`, h1 to h6) and how many; a
 * note's deeper headings take the last of them.
 * @typedef {{ top: number, count: number }} Heading
 */

/** Under a screen's title: h2 to h4. @type {Heading} */
export const HEADINGS = { top: 2, count: 3 };

/** Without a caller's own: a page shown by its name alone, out of reach. @type {Pages} */
export const noPages = (page) => ({ href: '', tip: page, off: true, why: 'Opens in MoolaKata' });

const MARKS = /** @type {Record<string, (c: any) => any>} */ ({
  bold: (c) => html`<strong>${c}</strong>`,
  italic: (c) => html`<em>${c}</em>`,
  underline: (c) => html`<u>${c}</u>`,
  strike: (c) => html`<s>${c}</s>`,
  highlight: (c) => html`<mark class="note-mark">${c}</mark>`,
  mono: (c) => html`<span class="note-mono">${c}</span>`,
});

/**
 * A link drawn: an address in a new tab, its address its tooltip; a page in place, or as its
 * text, greyed, saying why.
 * @param {any} attrs @param {any} c @param {Pages} pages @param {(page: string) => void} [open]
 */
function link(attrs, c, pages, open) {
  if (attrs?.href) {
    return html`
      <a href=${attrs.href} target="_blank" rel="noopener noreferrer nofollow"
        data-tip=${attrs.href}>${c}</a>
    `;
  }
  const p = pages(attrs?.page ?? '');
  if (p.off) {
    return html`<span class="note-link off" tabindex="0" data-tip=${`${p.tip} · ${
      p.why ?? 'Not shared with you'
    }`}>${c}</span>`;
  }
  return html`<a href=${p.href} data-tip=${p.tip} onClick=${(/** @type {MouseEvent} */ e) => {
    if (!open || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    open(attrs.page);
  }}>${c}</a>`;
}

/**
 * The elements of a node, its marks wrapped round its text in their order.
 * @param {any} n @param {Pages} pages @param {((page: string) => void) | undefined} open
 * @param {number} key @param {Heading} heading
 * @returns {any}
 */
function draw(n, pages, open, key, heading) {
  const kids = () => (n.content ?? []).map((c, i) => draw(c, pages, open, i, heading));
  switch (n.type) {
    case 'text': {
      let out = n.text;
      for (const m of [...(n.marks ?? [])].reverse()) {
        out = m.type === 'link' ? link(m.attrs, out, pages, open) : (MARKS[m.type]?.(out) ?? out);
      }
      return out;
    }
    case 'break':
      return html`<br key=${key} />`;
    case 'paragraph':
      return html`<p key=${key}>${kids()}</p>`;
    case 'heading': {
      // The levels this screen gives a note's headings: from `top`, `count` of them, the rest
      // drawn as the last; never past h6. The note's own level rides along, for a copy.
      const level = Math.min(Math.max(Number(n.attrs?.level) || 1, 1), heading.count);
      const H = `h${Math.min(heading.top + level - 1, 6)}`;
      return html`<${H} key=${key} data-note-level=${n.attrs?.level}>${kids()}</${H}>`;
    }
    case 'pre':
      return html`<pre key=${key} class="note-pre">${kids()}</pre>`;
    case 'quote':
      return html`<blockquote key=${key}>${kids()}</blockquote>`;
    case 'bullets':
      return html`<ul key=${key}>${kids()}</ul>`;
    case 'numbers':
      return html`<ol key=${key}>${kids()}</ol>`;
    case 'item':
      return html`<li key=${key}>${kids()}</li>`;
    default:
      return null;
  }
}

/**
 * A note read. Nothing in it is ever taken as markup: each kind of block and mark is drawn by
 * its own element, and anything else is left out.
 * @param {{ doc: any, pages?: Pages, open?: (page: string) => void, empty?: any,
 *   id?: string, heading?: Heading }} p
 */
export function NoteView({ doc, pages = noPages, open, empty = null, id, heading = HEADINGS }) {
  const blocks = doc?.type === 'doc' ? doc.content ?? [] : [];
  if (!blocks.length) return empty;
  return html`<div class="note-text note-read" id=${id}>${
    blocks.map((b, i) => draw(b, pages, open, i, heading))
  }</div>`;
}
