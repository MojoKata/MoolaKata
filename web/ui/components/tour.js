// Tours (requirements S12.17): a pane beside the page, inside what a dialog masks, that leads
// through a task spanning screens. Its links move around the app and it stays as it was; it
// follows the server through the live stream. ✕ closes it; its left edge drags its width.
// The first is Find uses (S12.17.6), for a category.
import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { html } from '../app/html.js';
import { guides } from '../app/config.js';
import { useApi } from '../app/hooks.js';
import { tourWidth } from '../store/prefs.js';
import { endTour, tour } from '../store/tour.js';
import { useCounts, useSteps, usesWords } from '../app/categories.js';
import { CategoryDialog, useCategories } from './categories.js';
import { openDialog } from './dialog.js';
import { Failed, Loading } from './bits.js';
import { Icon } from './icon.js';
import { render } from './markdown.js';

/** The tour open in this tab, if any. */
export function TourPane() {
  const t = tour.value;
  if (!t) return null;
  return html`<${FindUses} catId=${t.catId} start=${t.start} />`;
}

/**
 * The pane every tour draws in: its name as the title, ✕, and the edge that drags its width,
 * as the help pane's does (S12.7.1).
 * @param {{ title: string, children: any }} p
 */
function TourFrame({ title, children }) {
  const drag = (/** @type {PointerEvent} */ e) => {
    e.preventDefault();
    const x0 = e.clientX, w0 = tourWidth.value;
    const move = (/** @type {PointerEvent} */ m) => {
      tourWidth.value = Math.round(Math.max(260, Math.min(innerWidth / 2, w0 + x0 - m.clientX)));
    };
    const up = () => {
      removeEventListener('pointermove', move);
      removeEventListener('pointerup', up);
    };
    addEventListener('pointermove', move);
    addEventListener('pointerup', up);
  };
  const keys = (/** @type {KeyboardEvent} */ e) => {
    if (e.key === 'ArrowLeft') tourWidth.value = Math.min(innerWidth / 2, tourWidth.value + 20);
    if (e.key === 'ArrowRight') tourWidth.value = Math.max(260, tourWidth.value - 20);
  };
  return html`
    <aside class="tour" aria-label=${title} style=${{ width: tourWidth.value + 'px' }}>
      <div class="resizer" role="separator" aria-orientation="vertical"
        aria-label="Width of the tour" tabindex="0" onPointerDown=${drag} onKeyDown=${keys}></div>
      <header>
        <h2>${title}</h2>
        <button type="button" class="icon-btn" aria-label="Close the tour" data-tip="Close the tour"
          onClick=${endTour}><${Icon} name="x" /></button>
      </header>
      ${children}
    </aside>
  `;
}

/** A tour's words, shipped beside the guides (S12.17.5). @param {string} name */
function useWords(name) {
  const [md, setMd] = useState(/** @type {string | null} */ (null));
  useEffect(() => {
    let live = true;
    fetch(`${guides}/tour-${name}.md`).then((r) => (r.ok ? r.text() : '')).then(
      (text) => live && setMd(text),
      () => live && setMd(''),
    );
    return () => {
      live = false;
    };
  }, [name]);
  return md;
}

/**
 * Find uses (S12.17.6): what files money under a category that the reader can see, by kind,
 * each linked to where it is, the counts falling as they clear; and how many they can't see.
 * @param {{ catId: string, start?: Record<string, number> }} p
 */
function FindUses({ catId, start }) {
  const cats = useCategories();
  const cat = cats.byId[catId];
  // The stream says when the reader's saves, imports or the categories change: read again.
  const res = useApi(`/categories/${catId}/uses`, {}, ['saved', 'category', 'import']);
  const u = /** @type {any} */ (res.data);
  const words = useWords('uses');
  const { url } = useLocation();
  // What it found when it started, kept with the tour, so a step done since stays, ticked.
  useEffect(() => {
    if (u && !start && tour.value?.catId === catId) {
      tour.value = { ...tour.value, start: useCounts(u) };
    }
  }, [u, start]);
  const name = cat?.path || 'a category';
  if (u?.gone) {
    return html`
      <${TourFrame} title="Find uses">
        <p class="small">The category is gone: deleted, or merged into another.</p>
        </${TourFrame}>
    `;
  }
  const first = start || (u ? useCounts(u) : null);
  const steps = u && first ? useSteps(u, first, catId) : [];
  const link = (/** @type {{ label: string, href: string }} */ l) =>
    html`
      <a href=${l.href} class=${l.href === url ? 'here' : ''}
        aria-current=${l.href === url ? 'page' : undefined}>${l.label}</a>
    `;
  return html`
    <${TourFrame} title=${`Find uses of ${name}`}>
      ${words
        ? html`<div class="tour-words small">${
          render(words.replaceAll('{{category}}', name))
        }</div>`
        : null}
      ${res.error
        ? html`<${Failed} error=${res.error} />`
        : !u || !first
        ? html`<${Loading} lines=${4} />`
        : html`
          ${u.seen
            ? html`
              <p class="tour-left"><b>${u.seen}</b> of the ${Math.max(first.seen, u.seen)} uses you
                can see ${u.seen === 1 ? 'is' : 'are'} left.</p>
              <div class="bar"><i style=${{
                width: `${
                  (100 * (first.seen - Math.min(u.seen, first.seen))) / (first.seen || 1)
                }%`,
              }}></i></div>
              ${u.unseen
                ? html`<p class="small dim">${u.unseen} more you can't see: only their owners, or
                  an admin's merge, clear those.</p>`
                : null}
            `
            : html`
              <div class="notice">
                <${Icon} name="check" />
                <div><b>${`Nothing you can see uses ${name} now.`}</b></div>
              </div>
              ${u.unseen
                ? html`<p class="small">${
                  `${usesWords(0, u.unseen)} ${u.unseen === 1 ? 'is' : 'are'} left: an admin can` +
                  ' merge it into another category.'
                }</p>`
                : cat
                ? html`<p class="small">Nothing uses it: <button type="button" class="linklike"
                  onClick=${() => openDialog(CategoryDialog, { cat })}>open ${name}</button> to
                  delete it.</p>`
                : null}
            `}
          <ol class="tour-steps">${steps.map((s) =>
            html`
              <li class=${'tour-step' + (s.done ? ' done' : '')} key=${s.kind}>
                <h3><span class="tick" aria-hidden="true">${s.done ? '✓' : ''}</span>${s.title}<span
                    class="spacer"></span><span class="small dim">${s.done
                      ? 'done'
                      : s.count}</span></h3>
                ${s.items.length
                  ? html`<ul>${
                    s.items.map((it) =>
                      html`<li>${
                        it.links
                          ? html`${it.label}${
                            it.links.map((l, i) => html`${i ? ' · ' : ''}${link(l)}`)
                          }`
                          : link(/** @type {any} */ (it))
                      }</li>`
                    )
                  }</ul>`
                  : null}
              </li>
            `
          )}</ol>
        `}
    </${TourFrame}>
  `;
}
