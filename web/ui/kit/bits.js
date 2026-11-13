// Small shared pieces: tabs, filter chips, avatars, and what a card shows while it loads or
// when it failed.
import { html } from './html.js';
import { initials } from './format.js';
import { Icon } from './icon.js';

/**
 * Tabs as links, so each tab has its own address: the base and its key, or one of its own.
 * @param {{ tabs: ([string, string] | [string, string, string])[], current: string,
 *   base: string }} p
 */
export function Tabs({ tabs, current, base }) {
  return html`<div class="tabs" role="tablist">${
    tabs.map(([k, l, href]) =>
      html`
        <a role="tab" aria-selected=${k === current ? 'true' : 'false'} class=${'tab' +
          (k === current ? ' on' : '')} href=${href || `${base}/${k}`}
          data-v=${l}>${l}</a>
      `
    )
  }</div>`;
}

/**
 * @param {{ value: string, onChange: (v: string) => void, options: [string, string][],
 *   label: string }} p
 */
export function Chips({ value, onChange, options, label }) {
  return html`<div class="chips" role="group" aria-label=${label}>${
    options.map(([v, l]) =>
      html`
        <button type="button" class=${'chip' + (v === value ? ' on' : '')} aria-pressed=${v ===
            value
          ? 'true'
          : 'false'}
          onClick=${() => onChange(v)}>${l}</button>
      `
    )
  }</div>`;
}

// The theme's avatar hues (--av-1 to --av-7).
const HUES = [1, 2, 3, 4, 5, 6, 7].map((n) => `var(--av-${n})`);

/** @param {string} s */
function hue(s) {
  // FNV-1a: ids that share a long prefix still spread across the colours.
  let h = 2166136261;
  for (const c of s || '') h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0;
  return HUES[h % HUES.length];
}

/** @param {{ name: string, image?: string | null, id?: string, sm?: boolean, title?: string }} p */
export function Avatar({ name, image, id, sm, title }) {
  return html`<span class=${'avatar' + (sm ? ' sm' : '')} title=${title} style=${
    image ? undefined : { background: hue(id || name) }
  }>${image ? html`<img src=${image} alt="" />` : initials(name)}</span>`;
}

// An empty card or list's line (S12.19.2), drawn where everything else is.
export { Empty } from './state.js';

/** @param {{ lines?: number }} p */
export function Loading({ lines = 3 }) {
  return html`<div aria-busy="true" aria-label="Loading">${
    Array.from({ length: lines }, () => html`<div class="skeleton mt"></div>`)
  }</div>`;
}

/** @param {{ error: any }} p */
export function Failed({ error }) {
  return html`
    <div class="notice bad" role="alert">
      <${Icon} name="alert" />
      <div>${error?.message ||
        'This could not be loaded.'}${error?.errorId
        ? html`${' '}<span class="small dim">(${error.errorId})</span>`
        : null}</div>
    </div>
  `;
}
