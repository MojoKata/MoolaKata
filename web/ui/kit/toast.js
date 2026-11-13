// Toasts: short confirmations at the bottom of the page (requirements S12.1.2).
import { signal } from '@preact/signals';
import { html } from './html.js';

const toasts = signal(/** @type {{ id: number, text: string, leaving?: boolean }[]} */ ([]));
let n = 0;
/** How long a toast stays, and how long it takes to slide out (kit.css's toast-out). */
const STAYS = 3200, GOES = 240;

/** A line that slides up from the bottom, stays a moment and slides back out. @param {string} text */
export function toast(text) {
  const id = ++n;
  toasts.value = [...toasts.value, { id, text }];
  setTimeout(() => {
    toasts.value = toasts.value.map((t) => (t.id === id ? { ...t, leaving: true } : t));
    setTimeout(() => {
      toasts.value = toasts.value.filter((t) => t.id !== id);
    }, GOES);
  }, STAYS);
}

export function Toasts() {
  return html`<div class="toasts" role="status" aria-live="polite">${
    toasts.value.map((t) =>
      html`<div class=${'toast' + (t.leaving ? ' leaving' : '')} key=${t.id}>${t.text}</div>`
    )
  }</div>`;
}
