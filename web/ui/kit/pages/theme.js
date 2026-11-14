// The ui-kit's page for its theme (S17.3.10.1): every token, as the page has it now (dark or
// light), and every icon in the sprite.
import { useEffect, useState } from 'preact/hooks';
import { html } from '../html.js';
import { Icon } from '../icon.js';
import { Page } from './parts.js';

/** The tokens the theme sets on :root, read from its stylesheet. */
function tokens() {
  /** @type {string[]} */
  const names = [];
  for (const sheet of document.styleSheets) {
    let rules;
    try {
      rules = sheet.cssRules;
    } catch {
      continue;
    }
    const walk = (/** @type {CSSRuleList} */ list) => {
      for (const r of list) {
        if ('cssRules' in r && r.cssRules) walk(/** @type {any} */ (r).cssRules);
        const st = /** @type {any} */ (r).style;
        if (st && /** @type {any} */ (r).selectorText === ':root') {
          for (const p of st) if (p.startsWith('--') && !names.includes(p)) names.push(p);
        }
      }
    };
    walk(rules);
  }
  return names;
}

/** The icons the sprite holds. */
async function icons() {
  const sprite = document.getElementById('mk-icons');
  const doc = sprite ? sprite : new DOMParser().parseFromString(
    await (await fetch(new URL('../theme/icons.svg', import.meta.url))).text(),
    'image/svg+xml',
  );
  return [...doc.querySelectorAll('symbol')].map((s) => s.id.replace(/^i-/, ''));
}

export default function ThemePage() {
  const [names, setNames] = useState(/** @type {string[]} */ ([]));
  const [glyphs, setGlyphs] = useState(/** @type {string[]} */ ([]));
  useEffect(() => {
    setNames(tokens());
    icons().then(setGlyphs);
  }, []);
  const css = getComputedStyle(document.documentElement);
  return html`
    <${Page} title="Theme" about=${html`Every colour, size and radius is a custom property set
      on <code>:root</code> in <code>theme/tokens.css</code>, dark first and then light; the
      controls and the app draw only from them, so a theme is one file. Switch the page between
      dark and light above to see both.`}>
      <section class="demo" data-demo="tokens">
        <h3>Tokens</h3>
        <div class="tokens">${names.map((n) => {
          const v = css.getPropertyValue(n).trim();
          const colour = /^#|^rgb|^hsl/.test(v);
          return html`
            <div
              class="token">${colour
                ? html`<span class="swatch" style=${{ background: `var(${n})` }}></span>`
                : html`<span class="swatch none"></span>`}<code>${n}</code><span class="small dim">${v}</span></div>
          `;
        })}</div>
      </section>
      <section class="demo" data-demo="icons">
        <h3>Icons</h3>
        <div class="glyphs">${glyphs.map((g) =>
          html`<div class="glyph"><${Icon} name=${g} /><code>${g}</code></div>`
        )}</div>
      </section>
      </${Page}>
  `;
}
