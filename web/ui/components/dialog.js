// Dialogs (requirements S12.1.3): one at a time, trapping focus and returning it when closed.
// A dialog masks the content, not the guide beside it: the sidebar and the page are out of reach
// while it is open, and Tab goes round the dialog and the help pane. openDialog() resolves with
// what the dialog closes with.
import { signal } from '@preact/signals';
import { useEffect, useRef, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { paneWidth } from './help.js';
import { Icon } from './icon.js';

const FOCUSABLE =
  'a[href],button,input:not([type=hidden]),select,textarea,summary,[tabindex],[contenteditable]';

/**
 * The first and last places Tab stops in a part of the page.
 * @param {Element | null} part
 * @returns {(HTMLElement | undefined)[]}
 */
function ends(part) {
  const all = /** @type {HTMLElement[]} */ ([...(part?.querySelectorAll(FOCUSABLE) || [])])
    .filter((x) => x.tabIndex >= 0 && !(/** @type {any} */ (x).disabled) && x.offsetParent);
  return [all[0], all.at(-1)];
}

/** @type {import('@preact/signals').Signal<{ comp: any, props: any, resolve: (v: any) => void,
 *   back: HTMLElement | null } | null>} */
export const current = signal(null);

/**
 * @param {any} comp  a component taking { close, ...props }
 * @param {any} [props]
 * @returns {Promise<any>}
 */
export function openDialog(comp, props = {}) {
  return new Promise((resolve) => {
    current.value = {
      comp,
      props,
      resolve,
      back: /** @type {HTMLElement | null} */ (document.activeElement),
    };
  });
}

/** Whether the open dialog holds changes not saved (S12.15.6); set by the dialog itself. */
let unsaved = () => false;

/** Whether the open dialog holds changes not saved: they are lost if the session ends now. */
export function dialogHasChanges() {
  return !!current.value && unsaved();
}

/** @param {any} [value] */
export function closeDialog(value) {
  const d = current.value;
  if (!d) return;
  current.value = null;
  d.resolve(value);
  setTimeout(() => d.back?.focus?.(), 0);
}

export function DialogHost() {
  const d = current.value;
  if (!d) return null;
  const C = d.comp;
  return html`<${C} ...${d.props} close=${closeDialog} />`;
}

/**
 * The frame every dialog draws in.
 * `changed`, for a dialog that edits a draft (S12.15.6), says whether it holds changes not
 * saved: then Escape, ✕ or the browser's Back ask before closing, a click on the dimmed
 * content does nothing, and leaving the page brings the browser's own question.
 * @param {{ title: string, wide?: boolean, guide?: string, close: (v?: any) => void,
 *   footer?: any, note?: any, children: any, onSubmit?: () => void,
 *   changed?: () => boolean }} p
 */
export function Dialog({ title, wide, close, footer, note, children, onSubmit, changed }) {
  const box = useRef(/** @type {HTMLDivElement | null} */ (null));
  const [asking, setAsking] = useState(false);
  const askingRef = useRef(false);
  askingRef.current = asking;
  const keep = useRef(/** @type {HTMLButtonElement | null} */ (null));
  useEffect(() => {
    if (asking) keep.current?.focus();
  }, [asking]);
  // The latest `changed`: the dialog's draft may load after the first draw.
  const changedRef = useRef(changed);
  changedRef.current = changed;
  const has = () => !!changedRef.current?.();
  // Escape, ✕ or Back: closes, or asks first while there are changes.
  const leave = () => (has() ? setAsking(true) : close());
  useEffect(() => {
    if (!changed) return;
    unsaved = has;
    // Back goes to the entry the dialog adds, so it can be asked about; the entry goes with it.
    const mark = { mkDialog: Math.random() };
    history.pushState(mark, '', location.href);
    const onPop = () => {
      if (history.state?.mkDialog === mark.mkDialog) return;
      if (has()) {
        history.pushState(mark, '', location.href);
        setAsking(true);
      } else close();
    };
    const onUnload = (/** @type {BeforeUnloadEvent} */ e) => {
      if (has()) e.preventDefault();
    };
    addEventListener('popstate', onPop);
    addEventListener('beforeunload', onUnload);
    return () => {
      removeEventListener('popstate', onPop);
      removeEventListener('beforeunload', onUnload);
      unsaved = () => false;
      if (history.state?.mkDialog === mark.mkDialog) history.back();
    };
  }, []);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const first = el.querySelector(
      'input:not([type=hidden]),select,textarea,button:not(.dialog-x)',
    );
    /** @type {HTMLElement | null} */ (first)?.focus();
    // Everything in the frame but the help pane: the sidebar and the page.
    const masked =
      /** @type {HTMLElement[]} */ ([...document.querySelectorAll('.app > :not(.help)')]);
    for (const m of masked) m.inert = true;
    const onKey = (/** @type {KeyboardEvent} */ e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        if (askingRef.current) setAsking(false);
        else leave();
      } else if (e.key === 'Tab') {
        // Round the dialog's fields, then the guide's links and terms, and back.
        const [d0, d1] = ends(el);
        const [g0, g1] = ends(document.querySelector('.app > .help'));
        // From the end of one part to the start of the other; round the dialog alone without one.
        const to = new Map(e.shiftKey ? [[d0, g1 || d1], [g0, d1]] : [[d1, g0 || d0], [g1, d0]])
          .get(/** @type {HTMLElement} */ (document.activeElement));
        if (to) {
          e.preventDefault();
          to.focus();
        }
      }
    };
    // On the document: a button that disables while it works drops the focus to the body.
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      for (const m of masked) m.inert = false;
    };
  }, []);
  // The mask stops at the help pane, which stays in reach, and so isn't hidden from screen
  // readers either: the masked content is inert instead.
  const beside = paneWidth.value;
  return html`
    <div class="scrim" style=${{ right: beside + 'px' }} onClick=${(/** @type {any} */ e) =>
      e.target === e.currentTarget && !has() && close()}>
      <div class=${'dialog' + (wide ? ' wide' : '')} role="dialog"
        aria-modal=${beside ? undefined : 'true'} aria-labelledby="dialog-title" ref=${box}>
        <form onSubmit=${(/** @type {Event} */ e) => {
          e.preventDefault();
          onSubmit?.();
        }} class="dialog-form">
            <header><h2 id="dialog-title">${title}</h2>
              <button type="button" class="icon-btn dialog-x" aria-label="Close" onClick=${() =>
                leave()}><${Icon} name="x" /></button></header>
            <div class="body">${children}</div>
            ${footer !== null
              ? html`<footer>${
                note ? html`<span class="note">${note}</span>` : null
              }${footer}</footer>`
              : null}
          </form>
        ${asking
          ? html`
            <div class="dialog-ask" role="alertdialog" aria-labelledby="dialog-ask-title">
              <div class="dialog-ask-box">
                <h3 id="dialog-ask-title">Discard your changes?</h3>
                <p class="small dim">What you changed in this dialog isn't saved.</p>
                <div class="dialog-ask-buttons">
                  <button type="button" class="btn danger" onClick=${() => close()}>Discard</button>
                  <button type="button" class="btn primary" ref=${keep}
                    onClick=${() => setAsking(false)}>Keep editing</button>
                </div>
              </div>
            </div>
          `
          : null}
      </div>
    </div>
  `;
}
