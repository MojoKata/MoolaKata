// Styled tooltips that also show on keyboard focus and reach screen readers (S12.1.3): any
// element with data-tip shows it; the text is also its aria-label when it has no text of its own.
import { signal } from '@preact/signals';
import { html } from './html.js';

const tip = signal(/** @type {{ text: string, x: number, y: number } | null} */ (null));

/** @param {Event} e */
function show(e) {
  const el = /** @type {HTMLElement} */ (e.target)?.closest?.('[data-tip]');
  if (!el) return;
  const r = el.getBoundingClientRect();
  tip.value = { text: el.getAttribute('data-tip') || '', x: r.left, y: r.bottom + 6 };
}

function hide() {
  tip.value = null;
}

/** Show an element's tooltip now, as a refused key does while the field has the focus. @param {HTMLElement} el */
export function showTip(el) {
  show(/** @type {any} */ ({ target: el }));
}

/** Hide the tooltip shown, as a change to a marked field does. */
export const hideTip = hide;

export function installTooltips() {
  document.addEventListener('mouseover', show);
  document.addEventListener('focusin', show);
  document.addEventListener('mouseout', hide);
  document.addEventListener('focusout', hide);
}

export function TooltipHost() {
  const t = tip.value;
  if (!t) return null;
  return html`<div class="tooltip" role="tooltip" style=${{
    left: Math.min(t.x, innerWidth - 330) + 'px',
    top: t.y + 'px',
  }}>${t.text}</div>`;
}
