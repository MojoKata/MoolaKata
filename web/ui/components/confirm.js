// The question before anything is deleted, removed, revoked, ended or reset (requirements
// S12.16): one small box over the page or the dialog it comes from, No focused and the
// default (Enter and Escape both answer it), Yes named for what it does.
import { signal } from '@preact/signals';
import { useEffect, useRef } from 'preact/hooks';
import { html } from '../app/html.js';

/** @type {import('@preact/signals').Signal<{ title: string, detail?: string, yes: string,
 *   resolve: (v: boolean) => void, back: HTMLElement | null } | null>} */
const asked = signal(null);

/**
 * Ask before a destructive action; true only for Yes.
 * @param {{ title: string, detail?: string, yes?: string }} q
 * @returns {Promise<boolean>}
 */
export function confirmAction({ title, detail, yes = 'Yes, delete' }) {
  return new Promise((resolve) => {
    asked.value?.resolve(false);
    asked.value = {
      title,
      detail,
      yes,
      resolve,
      back: /** @type {HTMLElement | null} */ (document.activeElement),
    };
  });
}

/** @param {boolean} answer */
function answer(answer) {
  const q = asked.value;
  if (!q) return;
  asked.value = null;
  q.resolve(answer);
  setTimeout(() => q.back?.focus?.(), 0);
}

export function ConfirmHost() {
  const q = asked.value;
  const no = useRef(/** @type {HTMLButtonElement | null} */ (null));
  const yes = useRef(/** @type {HTMLButtonElement | null} */ (null));
  useEffect(() => {
    if (!q) return;
    no.current?.focus();
    // Ahead of a dialog's own keys, so Escape answers No here and leaves the dialog open.
    const onKey = (/** @type {KeyboardEvent} */ e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopImmediatePropagation();
        answer(false);
      } else if (e.key === 'Tab') {
        e.preventDefault();
        e.stopImmediatePropagation();
        (document.activeElement === no.current ? yes : no).current?.focus();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [q]);
  if (!q) return null;
  return html`
    <div class="confirm-scrim" onClick=${(/** @type {any} */ e) =>
      e.target === e.currentTarget && answer(false)}>
      <div class="dialog-ask-box" role="alertdialog" aria-modal="true"
        aria-labelledby="confirm-title" aria-describedby=${q.detail ? 'confirm-detail' : undefined}>
        <h3 id="confirm-title">${q.title}</h3>
        ${q.detail ? html`<p class="small dim" id="confirm-detail">${q.detail}</p>` : null}
        <div class="dialog-ask-buttons">
          <button type="button" class="btn danger" ref=${yes} onClick=${() => answer(true)}>${q
            .yes}</button>
          <button type="button" class="btn primary" ref=${no} onClick=${() =>
            answer(false)}>No</button>
        </div>
      </div>
    </div>
  `;
}
