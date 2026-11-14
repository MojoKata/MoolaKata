// The one popup menu (requirements S12.1.3): it closes on choosing, Escape, or a click or focus
// outside it.
import { signal } from '@preact/signals';
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { html } from './html.js';

/** @type {import('@preact/signals').Signal<{ x: number, y: number, above: number, items: any[], back: any } | null>} */
const open = signal(null);

/**
 * @param {MouseEvent | KeyboardEvent} e  the event on the button that opens it
 * @param {{ label: string, onSelect?: () => void, href?: string, target?: string, content?: any,
 *   on?: boolean, head?: boolean }[]} items
 */
export function openMenu(e, items) {
  const el = /** @type {HTMLElement} */ (e.currentTarget);
  const r = el.getBoundingClientRect();
  open.value = { x: r.left, y: r.bottom + 4, above: r.top - 4, items, back: el };
}

function close() {
  const m = open.value;
  open.value = null;
  m?.back?.focus?.();
}

export function MenuHost() {
  const ref = useRef(/** @type {HTMLDivElement | null} */ (null));
  const m = open.value;
  // Under its button, or above it where the window has no room below.
  const [top, setTop] = useState(/** @type {number | null} */ (null));
  useLayoutEffect(() => {
    const h = ref.current?.offsetHeight ?? 0;
    setTop(m && m.y + h > innerHeight && m.above - h >= 0 ? m.above - h : null);
  }, [m]);
  useEffect(() => {
    if (!m) return;
    /** @type {HTMLElement | null} */ (ref.current?.querySelector('button,a'))?.focus();
    const outside = (/** @type {Event} */ e) => {
      if (ref.current && !ref.current.contains(/** @type {Node} */ (e.target))) open.value = null;
    };
    const key = (/** @type {KeyboardEvent} */ e) => e.key === 'Escape' && close();
    document.addEventListener('mousedown', outside);
    document.addEventListener('focusin', outside);
    document.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('mousedown', outside);
      document.removeEventListener('focusin', outside);
      document.removeEventListener('keydown', key);
    };
  }, [m]);
  if (!m) return null;
  return html`<div class="menu" role="menu" ref=${ref} style=${{
    left: m.x + 'px',
    top: (top ?? m.y) + 'px',
  }}>
    ${
    m.items.map((it) =>
      it.head ? html`<div class="mh">${it.label}</div>` : it.href
        ? html`
          <a class="hh-item" role="menuitem" href=${it.href} target=${it.target}
            onClick=${() => (open.value = null)}>${it.content || it.label}</a>
        `
        : html`<button type="button" role="menuitem" class=${it.on ? 'on' : ''} onClick=${() => {
          // The focus goes back to the menu's button first: what the item opens (a dialog)
          // then takes it, and gives it back there.
          close();
          it.onSelect?.();
        }}>${it.label}</button>`
    )
  }
  </div>`;
}
