// A guide's acronym (requirements S12.7.7): its first use under a heading has a dashed
// underline, later ones show it on hover; on hover, or keyboard focus of the first, a card says
// what it stands for and what it means, with an external-link icon to the official document
// where there is one. The card follows the term in the page, so Tab reaches its link, and stays
// open while the pointer or focus is on either; Escape closes it. It moves with the term as the
// guide scrolls, and closes when the term scrolls out of sight.
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { Icon } from '../kit/icon.js';

/**
 * @typedef {{ title: string, text: string, source?: { label: string, href: string } }} Entry
 * @param {Entry & { term: string, word: string, quiet?: boolean }} props  `word` as the guide
 *   wrote it ("IRAs"); `quiet` for a later use under the same heading: no underline until
 *   hovered, and neither a tab stop nor read out again
 */
export function Term({ term, word, title, text, source, quiet = false }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const wrap = useRef(/** @type {HTMLElement | null} */ (null));
  const card = useRef(/** @type {HTMLElement | null} */ (null));
  const timer = useRef(/** @type {number | undefined} */ (undefined));
  const show = () => {
    clearTimeout(timer.current);
    setOpen(true);
  };
  // A moment's grace, so the pointer can cross from the term to its card.
  const hide = (delay = 150) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpen(false), delay);
  };

  /** Below the term, or above it when there's no room; false once the term is out of sight. */
  const place = () => {
    const el = card.current;
    const at = wrap.current?.firstElementChild;
    if (!el || !at) return false;
    const r = at.getBoundingClientRect();
    const view = at.closest('.help')?.getBoundingClientRect();
    if (view && (r.bottom < view.top || r.top > view.bottom)) return false;
    const below = r.bottom + 6;
    el.style.left = Math.max(8, Math.min(r.left, innerWidth - el.offsetWidth - 8)) + 'px';
    el.style.top =
      (below + el.offsetHeight <= innerHeight - 8
        ? below
        : Math.max(8, r.top - 6 - el.offsetHeight)) + 'px';
    return true;
  };

  useLayoutEffect(() => {
    if (open) place();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const follow = () => place() || setOpen(false);
    addEventListener('scroll', follow, true);
    return () => removeEventListener('scroll', follow, true);
  }, [open]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const leave = (/** @type {FocusEvent} */ e) => {
    if (!wrap.current?.contains(/** @type {Node | null} */ (e.relatedTarget))) hide(0);
  };
  const keys = (/** @type {KeyboardEvent} */ e) => {
    if (e.key === 'Escape' && open) {
      e.stopPropagation();
      setOpen(false);
    }
  };
  const link = source
    ? html`
      <a class="term-source" href=${source.href} target="_blank" rel="noopener noreferrer"
        aria-label=${`${source.label}, opens in a new tab`}>
        <${Icon} name="external" />
      </a>
    `
    : null;
  const abbr = quiet
    ? html`<abbr class="term quiet" data-term=${term}>${word}</abbr>`
    : html`<abbr class="term" tabindex="0" data-term=${term} aria-describedby=${id}>${word}<span
        class="sr-only"> (${title})</span></abbr>`;
  const tip = html`
    <span class="term-tip" ref=${card} hidden=${!open}>
      <span class="term-head">
        <span class="term-abbr">${term}</span><b>${title}</b>${link}
      </span><span class="term-text" id=${id}>${text}</span>
    </span>
  `;
  return html`
    <span class="term-wrap" ref=${wrap} onMouseEnter=${show} onMouseLeave=${() => hide()}
      onFocusIn=${show} onFocusOut=${leave} onKeyDown=${keys}>${abbr}${tip}</span>
  `;
}
