// Pasted markup made safe to read under the page's policy (requirements S12.18.15, S17.3.3): an
// inline style may not be applied, even in a document only parsed, so each `style` is renamed
// before parsing, what a note keeps of it (bold, italic, underline, strikethrough) becomes those
// elements, and the rest is dropped. A word processor's bold marked by a style alone (Google
// Docs) stays bold; its wrapper marked bold but drawn normal is unwrapped.

const KEPT = 'data-mk-style';

/**
 * The elements a style stands for, in the order they wrap: b, i, u, s.
 * @param {string} style
 */
export function styleTags(style) {
  const s = style.toLowerCase();
  const weight = /font-weight\s*:\s*([a-z0-9]+)/.exec(s)?.[1];
  /** @type {string[]} */
  const tags = [];
  if (weight && /^(bold|bolder|[6-9]00)$/.test(weight)) tags.push('b');
  if (/font-style\s*:\s*(italic|oblique)/.test(s)) tags.push('i');
  const deco = [...s.matchAll(/text-decoration(?:-line)?\s*:([^;]*)/g)].map((m) => m[1]).join(' ');
  if (/underline/.test(deco)) tags.push('u');
  if (/line-through/.test(deco)) tags.push('s');
  return { tags, normal: !!weight && /^(normal|lighter|[1-4]00)$/.test(weight) };
}

/**
 * Pasted markup with no inline style left: each one's bold, italic, underline and
 * strikethrough as elements round its content.
 * @param {string} html
 */
export function cleanPastedHTML(html) {
  const renamed = html.replace(/(<[a-z][^<>]*?\s)style(\s*=)/gi, `$1${KEPT}$2`);
  const doc = new DOMParser().parseFromString(renamed, 'text/html');
  for (const el of [...doc.body.querySelectorAll(`[${KEPT}]`)]) {
    const { tags, normal } = styleTags(el.getAttribute(KEPT) ?? '');
    el.removeAttribute(KEPT);
    let at = el;
    if (normal && /^(B|STRONG)$/.test(el.tagName)) {
      at = doc.createElement('span');
      el.replaceWith(at);
      at.append(...el.childNodes);
    }
    for (const t of tags.reverse()) {
      const w = doc.createElement(t);
      w.append(...at.childNodes);
      at.append(w);
    }
  }
  // Anything left with a style the rename missed loses it.
  for (const el of doc.body.querySelectorAll('[style]')) el.removeAttribute('style');
  return doc.body.innerHTML;
}
