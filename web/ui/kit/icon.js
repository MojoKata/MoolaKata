// Icons: one SVG sprite, the theme's (requirements S17.3.6), beside this module.
import { html } from './html.js';

// A page that carries the sprite itself (the generated mockup) names it by id alone; otherwise
// the file is loaded from beside the kit.
const sprite = document.getElementById('mk-icons')
  ? ''
  : new URL('./theme/icons.svg', import.meta.url).pathname;

/** @param {{ name: string, cls?: string, label?: string }} p */
export function Icon({ name, cls = '', label }) {
  return html`
    <svg class=${'i ' + cls} aria-hidden=${label ? undefined : 'true'} role=${label
      ? 'img'
      : undefined} aria-label=${label}>
      <use href=${`${sprite}#i-${name}`} />
    </svg>
  `;
}
