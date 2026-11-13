// Re-authentication (requirements S13.7.2): an action that needs the password again when it was
// last given over 10 minutes ago asks for it, then runs again.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useSubmit } from '../app/hooks.js';
import { Dialog, openDialog } from '../kit/dialog.js';
import { Field, FormError, Input } from '../kit/fields.js';

/** @param {{ close: (v?: any) => void }} p */
function Reauth({ close }) {
  const [password, setPassword] = useState('');
  const go = useSubmit(async () => {
    await api.post('/session/reauth', { password });
    close(true);
  });
  return html`
    <${Dialog} title="Your password again" close=${close}
      onSubmit=${() => go.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${go.busy || !password}>Go on</button>`}>
      <p class="small dim" style=${{ marginTop: 0 }}>This needs your password: it was given over
        10 minutes ago.</p>
      <${Field} label="Your password" id="reauth-password">
        <${Input} type="password" value=${password} onInput=${setPassword}
          autocomplete="current-password" required />
        </${Field}>
        <${FormError} error=${go.error} />
        </${Dialog}>
  `;
}

/**
 * Run an action; asked for the password again, ask the user and run it once more.
 * @template T
 * @param {() => Promise<T>} action
 * @returns {Promise<T>}
 */
export async function withReauth(action) {
  try {
    return await action();
  } catch (e) {
    if (/** @type {any} */ (e).code !== 'reauth-required') throw e;
    if (!(await openDialog(Reauth, {}))) throw e;
    return await action();
  }
}
