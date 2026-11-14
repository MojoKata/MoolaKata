// Actions and the page's state (requirements S12.19): an action not open now is shown off with
// its reason, never hidden; what the page knows is shown briefly, its explanation in the guide.
import { html } from './html.js';
import { Icon } from './icon.js';

/**
 * A button (S12.19.1). Given `why`, it is shown but off: `aria-disabled`, so it still reaches
 * the keyboard, its click and Enter do nothing, and `why` is its tooltip and its description
 * for a screen reader. `class` is the button's (`btn`, `btn sm`, `icon-btn`, …).
 * @param {{ why?: string | null | false, class?: string, type?: string,
 *   onClick?: (e: any) => void, children?: any, [k: string]: any }} p
 */
export function Action({ why, class: cls = 'btn', type = 'button', onClick, children, ...rest }) {
  if (!why) {
    return html`<button type=${type} class=${cls} onClick=${onClick} ...${rest}>${children}</button>`;
  }
  // A submit that is off mustn't submit: it is a plain button while it is off.
  return html`
    <button type="button" class=${cls} ...${rest} aria-disabled="true" data-tip=${why}
      aria-description=${why}
      onClick=${(/** @type {Event} */ e) => e.preventDefault()}>${children}</button>
  `;
}

/**
 * Nothing here yet (S12.19.2): a short line where the content would be, with the action that
 * makes the first one when there is one.
 * @param {{ children: any, action?: any }} p
 */
export function Empty({ children, action }) {
  return html`<div class="empty"><span>${children}</span>${
    action ? html`<span class="empty-action">${action}</span>` : null
  }</div>`;
}

/**
 * A count or a status (S12.19.3): a pill whose one sentence of explanation is its tooltip,
 * reached by Tab. `tone` is the pill's colour: ok, warn, bad, info.
 * @param {{ children: any, why: string, tone?: string }} p
 */
export function StatePill({ children, why, tone }) {
  return html`
    <span class=${'pill' + (tone ? ' ' + tone : '')} tabindex="0" data-tip=${why}
      aria-description=${why}>${children}</span>
  `;
}

/**
 * Something needing attention (S12.19.4): a notice of one line naming it, its actions after
 * it. `tone` is warn (the default) or bad.
 * @param {{ children: any, actions?: any, tone?: string, icon?: any }} p
 */
export function Attention({ children, actions, tone = 'warn', icon }) {
  return html`<div class=${'notice attention ' + tone} role="status">${icon || null}<span
    class="grow">${children}</span>${
    actions ? html`<span class="attention-actions">${actions}</span>` : null
  }</div>`;
}

/**
 * Opening a record from its row (S12.19.5): an icon-only button at the row's end, never a
 * click on the row. A pencil for a record the person may change, which opens it to edit; an
 * eye for one they may only read, which opens it read (S12.18.6). Its name says which, and
 * whose: "Edit Whole Foods", "View Whole Foods". `why` shows it off, saying why: a row with
 * nothing to read yet that the person may not make (S12.19.1).
 * `label` names a pencil that edits only part of it ("Leave Rent out of your budgets").
 * @param {{ name: string, read?: boolean, why?: string | null, label?: string,
 *   onClick: () => void, [k: string]: any }} p
 */
export function RowTool({ name, read, why, label: own, onClick, ...rest }) {
  const label = own || `${read ? 'View' : 'Edit'} ${name}`;
  return html`
    <${Action} class="icon-btn row-tool" aria-label=${label} data-tip=${label} why=${why}
      onClick=${onClick} ...${rest}>
      <${Icon} name=${read ? 'eye' : 'pencil'} />
      </${Action}>
  `;
}
