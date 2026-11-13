// Toasts: short confirmations at the bottom of the page (requirements S12.1.2).
import { signal } from '@preact/signals';
import { html } from './html.js';

const toasts = signal(/** @type {{ id: number, text: string }[]} */ ([]));
let n = 0;

/** @param {string} text */
export function toast(text) {
  const id = ++n;
  toasts.value = [...toasts.value, { id, text }];
  setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id);
  }, 3200);
}

export function Toasts() {
  return html`<div class="toasts" role="status" aria-live="polite">${
    toasts.value.map((t) => html`<div class="toast" key=${t.id}>${t.text}</div>`)
  }</div>`;
}
