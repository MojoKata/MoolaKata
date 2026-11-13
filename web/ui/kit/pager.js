// The pager for long lists (requirements S12.1.3, S13.8.5): a page size of 100, 500 or 1000
// (the caller keeps it, in a signal), the rows shown out of the list's total with a jump to its pages, and rows that arrived while reading
// counted on an orange +N new pill instead of shifting the page: the screen adds them to its
// offset (`offsetOf`).
import { html } from './html.js';

/**
 * The pages to offer: the first two, this one and the next two, ten on, and the last two.
 * @param {number} page @param {number} pages
 */
function jumps(page, pages) {
  const want = [1, 2, page - 1, page, page + 1, page + 2, page + 10, pages - 1, pages];
  return [...new Set(want)].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
}

/**
 * Where page `page` starts, `size` rows to a page, with the rows that arrived since the first
 * page was read.
 * @param {number} page @param {number} size @param {number} [newer]
 */
export function offsetOf(page, size, newer = 0) {
  return (page - 1) * size + (page > 1 ? newer : 0);
}

/**
 * `size` holds the page size, which the pager changes.
 * @param {{ shown: number, page: number, total: number, onPage: (n: number) => void,
 *   size: { value: number }, newer?: number, onNewer?: () => void, label: string }} p
 */
export function Pager({ shown, page, total, onPage, size, newer = 0, onNewer, label }) {
  const pageSize = size;
  const first = (page - 1) * pageSize.value + 1;
  const pages = Math.max(1, Math.ceil(total / pageSize.value));
  return html`<div class="pager">
    <label class="small dim" for=${'pg-' + label}>Page size</label>
    <select class="in" id=${'pg-' + label} style=${{ width: '90px', height: '30px' }}
      value=${String(pageSize.value)} onChange=${(/** @type {any} */ e) => {
    pageSize.value = Number(e.currentTarget.value);
    onPage(1);
  }}>
      ${[100, 500, 1000].map((n) => html`<option value=${n}>${n}</option>`)}
    </select>
    <span class="small dim">${shown ? `${first}–${first + shown - 1} of ${total}` : 'none'}</span>
    <div class="jump">
      <button type="button" disabled=${page <= 1} onClick=${() =>
    onPage(page - 1)} aria-label="Previous page">‹</button>
      ${
    jumps(page, pages).map((n) =>
      html`
        <button type="button" class=${n === page ? 'on' : ''} aria-current=${n === page
          ? 'page'
          : undefined} aria-label=${`Page ${n} of ${pages}`}
          onClick=${() => onPage(n)}>${n}</button>
      `
    )
  }
      <button type="button" disabled=${page >= pages} onClick=${() =>
    onPage(page + 1)} aria-label="Next page">›</button>
    </div>
    <span class="spacer"></span>${
    newer
      ? html`<button type="button" class="pill new" onClick=${onNewer}>+${newer} new</button>`
      : null
  }
  </div>`;
}
