// The ui-kit's pages (requirements S17.3.10.4): a list of them beside the one shown, chosen by
// the address (`#numbers`), with the theme switched between dark and light. The hosts the kit's
// overlays draw in sit here once, as an app's frame holds them.
import { render } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { html } from '../html.js';
import { ConfirmHost } from '../confirm.js';
import { DialogHost } from '../dialog.js';
import { MenuHost } from '../menu.js';
import { Toasts } from '../toast.js';
import { installTooltips, TooltipHost } from '../tooltip.js';
import { checkOnSubmit } from '../fields.js';
import NumbersPage from './numbers.js';
import TagsPage from './tags.js';
import DatesPage from './dates.js';
import FieldsPage from './fields.js';
import StatePage from './state.js';
import OverlaysPage from './overlays.js';
import ThemePage from './theme.js';

/** Every page, in the order listed. @type {[string, string, () => any][]} */
export const PAGES = [
  ['numbers', 'Numbers', NumbersPage],
  ['tags', 'Several of a list', TagsPage],
  ['dates', 'Dates and times', DatesPage],
  ['fields', 'Fields', FieldsPage],
  ['state', 'Actions and state', StatePage],
  ['overlays', 'Dialogs, menus and the rest', OverlaysPage],
  ['theme', 'Theme', ThemePage],
];

const chosen = () => {
  const id = location.hash.slice(1);
  return PAGES.some(([k]) => k === id) ? id : PAGES[0][0];
};

function Catalog() {
  const [id, setId] = useState(chosen);
  const [dark, setDark] = useState(true);
  useEffect(() => {
    const on = () => setId(chosen());
    addEventListener('hashchange', on);
    return () => removeEventListener('hashchange', on);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  }, [dark]);
  const [, title, P] = /** @type {[string, string, () => any]} */ (PAGES.find(([k]) => k === id));
  useEffect(() => {
    document.title = `${title} · ui-kit`;
  }, [title]);
  return html`
    <div class="kit">
      <nav class="kit-nav" aria-label="The ui-kit's pages">
        <div class="kit-brand">ui-kit</div>
        ${PAGES.map(([k, t]) =>
          html`
            <a href=${'#' + k} class=${'kit-link' + (k === id ? ' on' : '')}
              aria-current=${k === id ? 'page' : undefined}>${t}</a>
          `
        )}
        <button type="button" class="btn sm kit-theme" aria-pressed=${dark ? 'true' : 'false'}
          onClick=${() => setDark(!dark)}>${dark ? 'Dark' : 'Light'}</button>
      </nav>
      <main class="kit-main" key=${id}>
        <${P} />
      </main>
    </div>
    <${DialogHost} />
    <${ConfirmHost} />
    <${MenuHost} />
    <${Toasts} />
    <${TooltipHost} />
  `;
}

installTooltips();
checkOnSubmit();
render(html`<${Catalog} />`, /** @type {HTMLElement} */ (document.getElementById('kit')));
