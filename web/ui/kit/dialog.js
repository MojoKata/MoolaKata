// Dialogs (requirements S12.1.3, S12.15.7): trapping focus and returning it when closed. One
// opened from another opens over it: the one beneath waits, inert, and is back as it was when
// the one on top closes. A dialog masks the content, not what the app keeps beside it (its
// guide): the rest is out of reach while one is open, and Tab goes round the top dialog and
// what is beside it. openDialog() resolves with what the dialog closes with.
import { createContext } from 'preact';
import { computed, signal } from '@preact/signals';
import { useContext, useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { html } from './html.js';
import { IdPrefix } from './fields.js';
import { Icon } from './icon.js';

/**
 * Where the dialogs sit, which the app says once (`placeDialogs`): the part of the page kept in
 * reach beside them and its width, the parts masked while one is open, and whether something
 * outside the dialogs (a screen's form) holds changes not saved.
 * @type {{ beside: () => Element | null, width: () => number, masked: () => HTMLElement[],
 *   changes: () => boolean }}
 */
let place = { beside: () => null, width: () => 0, masked: () => [], changes: () => false };
/** @param {Partial<typeof place>} p */
export function placeDialogs(p) {
  place = { ...place, ...p };
}

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

/** @typedef {{ comp: any, props: any, resolve: (v: any) => void, back: HTMLElement | null,
 *   key: number }} Open */

/** The dialogs open, the last on top. @type {import('@preact/signals').Signal<Open[]>} */
export const stack = signal([]);
/** The dialog on top, if any. */
export const current = computed(() => stack.value.at(-1) || null);
let opened = 0;

/**
 * @param {any} comp  a component taking { close, ...props }
 * @param {any} [props]
 * @returns {Promise<any>}
 */
export function openDialog(comp, props = {}) {
  return new Promise((resolve) => {
    stack.value = [...stack.value, {
      comp,
      props,
      resolve,
      back: /** @type {HTMLElement | null} */ (document.activeElement),
      key: ++opened,
    }];
  });
}

/** Whether each open dialog holds changes not saved (S12.15.6); set by the dialogs themselves. */
const unsaved = new Set(/** @type {(() => boolean)[]} */ ([]));

/** Whether an open dialog, or a screen's form, holds changes not saved: they are lost if the
 * session ends now. */
export function dialogHasChanges() {
  return [...unsaved].some((has) => has()) || place.changes();
}

/** The history entries the dialogs add: this page's, and each one's place, the later higher. */
const PAGE = Math.random();
let marks = 0;

/** The history entry a closing dialog takes back with it, while it goes (a Promise). */
let leaving = Promise.resolve();

/**
 * Closes a dialog, and any opened over it, which close with nothing.
 * @param {Open} d @param {any} [value]
 */
function closeOne(d, value) {
  const at = stack.value.indexOf(d);
  if (at < 0) return;
  const gone = stack.value.slice(at);
  stack.value = stack.value.slice(0, at);
  // Once the dialog is gone and so is its history entry: a caller that goes somewhere next
  // isn't sent back by the entry's late `history.back()` (CR3-406).
  setTimeout(() => {
    leaving.then(() => {
      for (const x of gone.reverse()) x.resolve(x === d ? value : undefined);
      d.back?.focus?.();
    });
  }, 0);
}

/** Closes the dialog on top. @param {any} [value] */
export function closeDialog(value) {
  const d = stack.value.at(-1);
  if (d) closeOne(d, value);
}

/** Closes every open dialog, the ones beneath with nothing. */
export function closeAllDialogs() {
  const d = stack.value[0];
  if (d) closeOne(d);
}

/** Whether the dialog drawing here is the one on top. */
const OnTop = createContext(true);

export function DialogHost() {
  const all = stack.value;
  const open = all.length > 0;
  // Everything but what is kept beside the dialogs is out of reach while any dialog is open: set
  // and cleared in the same commit as the dialogs, never a frame late.
  useLayoutEffect(() => {
    if (!open) return;
    const masked = place.masked();
    for (const m of masked) m.inert = true;
    return () => {
      for (const m of masked) m.inert = false;
    };
  }, [open]);
  return all.map((d, i) => {
    const C = d.comp;
    const top = i === all.length - 1;
    // A dialog over another names its fields apart, so a label and the guide find its own.
    return html`
      <div class="dialog-layer" key=${d.key} inert=${!top}>
        <${OnTop.Provider} value=${top}>
          <${IdPrefix.Provider} value=${i ? `d${i}-` : ''}>
            <${C} ...${d.props} close=${(/** @type {any} */ v) => closeOne(d, v)} />
            </${IdPrefix.Provider}>
            </${OnTop.Provider}>
            </div>
    `;
  });
}

/**
 * The frame every dialog draws in.
 * `changed`, for a dialog that edits a draft (S12.15.6), says whether it holds changes not
 * saved: then Escape, ✕, Cancel (a footer button marked data-cancel) or the browser's Back ask
 * before closing, a click on the dimmed
 * content does nothing, and leaving the page brings the browser's own question.
 * `save`, for such a dialog, saves from the question (resolving to whether it saved). `size`
 * sets its width and least height where its content doesn't.
 * @param {{ title: string, wide?: boolean, guide?: string, close: (v?: any) => void,
 *   footer?: any, note?: any, children: any, onSubmit?: () => void,
 *   changed?: () => boolean, save?: () => Promise<boolean>,
 *   size?: { width?: string, minHeight?: string } }} p
 */
export function Dialog(
  { title, wide, close, footer, note, children, onSubmit, changed, save, size },
) {
  const box = useRef(/** @type {HTMLDivElement | null} */ (null));
  const top = useContext(OnTop);
  const topRef = useRef(top);
  topRef.current = top;
  const ids = useContext(IdPrefix);
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
    unsaved.add(has);
    // Back goes to the entry the dialog adds, so it can be asked about; the entry goes with it.
    const mark = { mkDialog: PAGE, at: ++marks };
    history.pushState(mark, '', location.href);
    const onPop = () => {
      // Back to this dialog's entry, or one above it (a dialog over it): not this one's.
      const st = history.state;
      if (st?.mkDialog === PAGE && st.at >= mark.at) return;
      // Beneath another dialog, Back is the top one's: this one keeps its entry.
      if (!topRef.current) {
        history.pushState(mark, '', location.href);
        return;
      }
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
      unsaved.delete(has);
      if (history.state?.mkDialog === PAGE && history.state.at === mark.at) {
        leaving = new Promise((done) => {
          addEventListener('popstate', () => done(undefined), { once: true });
          setTimeout(done, 1000); // a browser that never says: go on regardless
        });
        history.back();
      }
    };
  }, []);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const first = el.querySelector(
      'input:not([type=hidden]),select,textarea,button:not(.dialog-x)',
    );
    /** @type {HTMLElement | null} */ (first)?.focus();
    const onKey = (/** @type {KeyboardEvent} */ e) => {
      // A dialog beneath another hears nothing: the top one answers.
      if (!topRef.current) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        if (askingRef.current) setAsking(false);
        else leave();
      } else if (e.key === 'Tab') {
        // Round the dialog's fields, then what is beside it (the guide's links and terms), and back.
        const [d0, d1] = ends(el);
        const [g0, g1] = ends(place.beside());
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
    return () => document.removeEventListener('keydown', onKey);
  }, []);
  const [saving, setSaving] = useState(false);
  // Save from the question: saved, the dialog closes as its save closes it; refused or asking
  // first, the question goes and the dialog shows why (S12.15.6).
  const saveNow = async () => {
    if (!save) return;
    setSaving(true);
    try {
      if (!(await save())) setAsking(false);
    } finally {
      setSaving(false);
    }
  };
  // The mask stops at what is kept beside it, which stays in reach, and so isn't hidden from
  // screen readers either: the masked content is inert instead.
  const beside = place.width();
  return html`
    <div class="scrim" style=${{ right: beside + 'px' }} onClick=${(/** @type {any} */ e) =>
      e.target === e.currentTarget && !has() && close()}>
      <div class=${'dialog' + (wide ? ' wide' : '')} style=${size} role="dialog"
        aria-modal=${beside ? undefined : 'true'} aria-labelledby=${ids +
          'dialog-title'} ref=${box}>
        <form onSubmit=${(/** @type {Event} */ e) => {
          e.preventDefault();
          onSubmit?.();
        }} class="dialog-form">
            <header><h2 id=${ids + 'dialog-title'}>${title}</h2>
              <button type="button" class="icon-btn dialog-x" aria-label="Close" onClick=${() =>
                leave()}><${Icon} name="x" /></button></header>
            <div class="body">${children}</div>
            ${footer !== null
              ? html`<footer onClick=${(/** @type {any} */ e) => {
                // Cancel (a button marked data-cancel) asks first too, as Escape does.
                if (!e.target.closest?.('[data-cancel]')) return;
                e.preventDefault();
                leave();
              }}>${note ? html`<span class="note">${note}</span>` : null}${footer}</footer>`
              : null}
          </form>
        ${asking
          ? html`
            <div class="dialog-ask" role="alertdialog" aria-labelledby=${ids + 'dialog-ask-title'}>
              <div class="dialog-ask-box">
                <h3 id=${ids + 'dialog-ask-title'}>Save Your Changes?</h3>
                <p class="small dim">What you changed in this dialog isn't saved. Save it, or
                  discard it and go on.</p>
                <div class="dialog-ask-buttons">
                  <button type="button" class="btn" ref=${keep}
                    onClick=${() => setAsking(false)}>Keep Editing</button>
                  <button type="button" class="btn danger" onClick=${() => close()}>Discard</button>
                  ${save
                    ? html`
                      <button type="button" class="btn primary" disabled=${saving}
                        onClick=${saveNow}>Save</button>
                    `
                    : null}
                </div>
              </div>
            </div>
          `
          : null}
      </div>
    </div>
  `;
}
