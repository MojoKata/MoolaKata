// The help pane (requirements S12.7): F1 toggles it; it shows the guide of the screen, tab or
// dialog in view, and follows the focus to the field's heading. Its width drags (up to half the
// window) and moves with the arrow keys; the browser remembers both. The acronyms of
// guides/terms.md, and the IRS forms of guides/forms.md, show what they are on hover and focus.
import { signal } from '@preact/signals';
import { useEffect, useRef, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { guides } from '../app/config.js';
import { helpOpen, helpWidth } from '../store/prefs.js';
import { assemble, glossary, render } from './markdown.js';
import { Icon } from './icon.js';

/** The guide of the screen in view: its key, and values its parts need (the account type). */
export const screenGuide = signal(
  /** @type {{ key: string, vars?: Record<string, string> }} */ ({
    key: 'dashboard',
  }),
);
/** A dialog's guide, while it is open. */
export const dialogGuide = signal(/** @type {string | null} */ (null));
/** The help pane's width while it is on screen, else 0: where a dialog's mask stops (S12.1.3). */
export const paneWidth = signal(0);

/**
 * @param {string} key
 * @param {Record<string, string>} [vars]
 */
export function useGuide(key, vars) {
  const v = JSON.stringify(vars || {});
  useEffect(() => {
    screenGuide.value = { key, vars };
  }, [key, v]);
}

/** @param {string} key */
export function useDialogGuide(key) {
  useEffect(() => {
    dialogGuide.value = key;
    return () => {
      dialogGuide.value = null;
    };
  }, [key]);
}

const cache = new Map();
/** @param {string} name */
function load(name) {
  if (!cache.has(name)) {
    cache.set(
      name,
      fetch(`${guides}/${name}.md`).then((r) => {
        if (!r.ok) throw new Error(`no guide ${name}`);
        return r.text();
      }),
    );
  }
  return cache.get(name);
}

export function HelpPane() {
  const ref = useRef(/** @type {HTMLElement | null} */ (null));
  // The guide drawn, with its key: `data-guide` names the guide shown, not the one asked for,
  // so whatever reads the pane after a change waits for the new guide's text.
  const [shown, setShown] = useState(
    /** @type {{ key: string, md: string } | null} */ (null),
  );
  const md = shown?.md ?? null;
  const [terms, setTerms] = useState(/** @type {import('./markdown.js').Glossary} */ (new Map()));
  const [forms, setForms] = useState(/** @type {import('./markdown.js').Glossary} */ (new Map()));
  const key = dialogGuide.value || screenGuide.value.key;
  const vars = dialogGuide.value ? {} : screenGuide.value.vars || {};

  // Without the terms or the forms a guide still shows, its acronyms and forms plain.
  useEffect(() => {
    load('terms').then((text) => setTerms(glossary(text)), () => {});
    load('forms').then((text) => setForms(glossary(text)), () => {});
  }, []);

  useEffect(() => {
    let live = true;
    load(key).then((text) => assemble(text, load, vars)).then(
      (text) => live && setShown({ key, md: text }),
      () => live && setShown({ key, md: `# ${key}\n\nThis screen's guide is missing.` }),
    );
    return () => {
      live = false;
    };
  }, [key, JSON.stringify(vars)]);

  // The active topic: the focused field's heading stays marked until another field's heading
  // takes over (S12.7.3). Headings are reused across guides, so a new guide marks afresh.
  const heading = (/** @type {Element | null} */ el) => {
    const id = el?.id?.startsWith('f-') ? el.id.slice(2) : el?.closest?.('[data-help]')
      ?.getAttribute('data-help');
    return id && ref.current ? ref.current.querySelector(`[data-anchor="${id}"]`) : null;
  };
  const mark = (/** @type {Element | null} */ target) => {
    ref.current?.querySelectorAll('h2.active').forEach((a) =>
      a !== target && a.classList.remove('active')
    );
    target?.classList.add('active');
  };

  useEffect(() => mark(heading(document.activeElement)), [md]);

  useEffect(() => {
    const el = /** @type {HTMLElement} */ (ref.current);
    const size = new ResizeObserver(() => (paneWidth.value = el.offsetWidth));
    size.observe(el);
    return () => {
      size.disconnect();
      paneWidth.value = 0;
    };
  }, []);

  useEffect(() => {
    const follow = (/** @type {FocusEvent} */ e) => {
      const target = heading(/** @type {HTMLElement} */ (e.target));
      if (!target) return;
      const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
      mark(target);
      target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
      target.classList.add('flash');
      setTimeout(() => target.classList.remove('flash'), 1200);
    };
    document.addEventListener('focusin', follow);
    return () => document.removeEventListener('focusin', follow);
  }, []);

  const drag = (/** @type {PointerEvent} */ e) => {
    e.preventDefault();
    const move = (/** @type {PointerEvent} */ m) => {
      helpWidth.value = Math.max(260, Math.min(innerWidth / 2, innerWidth - m.clientX));
    };
    const up = () => {
      removeEventListener('pointermove', move);
      removeEventListener('pointerup', up);
    };
    addEventListener('pointermove', move);
    addEventListener('pointerup', up);
  };
  const keys = (/** @type {KeyboardEvent} */ e) => {
    if (e.key === 'ArrowLeft') helpWidth.value = Math.min(innerWidth / 2, helpWidth.value + 20);
    if (e.key === 'ArrowRight') helpWidth.value = Math.max(260, helpWidth.value - 20);
  };

  return html`
    <aside class="help" aria-label="Help" ref=${ref} style=${{ width: helpWidth.value + 'px' }}>
      <div class="resizer" role="separator" aria-orientation="vertical" aria-label="Resize help"
        tabindex="0" onPointerDown=${drag} onKeyDown=${keys}></div>
      <button type="button" class="icon-btn help-close" aria-label="Close help (F1)"
        onClick=${() => (helpOpen.value = false)}><${Icon} name="x" /></button>
      <div class="guide" data-guide=${shown?.key}>${md === null ? null : render(
        md,
        (src) => /^https?:|^\//.test(src) ? src : `${guides}/${src}`,
        terms,
        forms,
      )}</div>
    </aside>
  `;
}

export function HelpCorner() {
  return html`
    <button type="button" class="help-corner" aria-label="Show help (F1)"
      data-tip="Show help (F1)" onClick=${() => (helpOpen.value = true)}><span></span></button>
  `;
}
