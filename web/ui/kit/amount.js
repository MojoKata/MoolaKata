// Amounts (requirements S12.4): tabular, the dollar sign, gains green and losses red and signed,
// so colour is never the only cue; blurred in privacy mode (S12.3).
import { html } from './html.js';
import { isNegative, money, pct } from './format.js';

/**
 * @param {{ v: string | null | undefined, signed?: boolean, cents?: boolean, cls?: string,
 *   title?: string }} p
 */
export function Amt({ v, signed = false, cents = true, cls = '', title }) {
  const tone = signed && v != null ? (isNegative(v) ? 'down' : 'up') : '';
  return html`<span class=${`amt ${tone} ${cls}`} title=${title}>${
    money(v, {
      sign: signed,
      cents,
    })
  }</span>`;
}

/** @param {{ v: string | null | undefined }} p */
export function Pct({ v }) {
  if (v == null) return html`<span class="dim">—</span>`;
  return html`<span class=${isNegative(v) ? 'down' : 'up'}>${pct(v)}</span>`;
}
