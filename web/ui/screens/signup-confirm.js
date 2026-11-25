// Confirming the email of a sign-up request (requirements S10.1.4): the request then waits for
// an admin, who approves or rejects it; an email says which. The username is checked only now,
// so a taken one is asked for again here before the request reaches the admins (S10.1.4.1).
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useSubmit } from '../app/hooks.js';
import { AuthCard, tokenFromHash } from '../components/auth.js';
import { errAt, Field, FormError, Input } from '../kit/fields.js';

export default function SignupConfirm() {
  const token = tokenFromHash();
  const [state, setState] = useState(/** @type {any} */ (null));
  const [taken, setTaken] = useState(/** @type {any} */ (null));
  const [username, setUsername] = useState('');
  /** @param {any} e */
  const failed = (e) => {
    if (e?.status === 422 && errAt(e, 'username')) setTaken(e);
    else setState(false);
  };
  useEffect(() => {
    api.post('/signup/confirm', { token }).then(setState, failed);
  }, []);
  const save = useSubmit(async () => {
    try {
      setState(await api.post('/signup/confirm', { token, username }));
    } catch (e) {
      if (/** @type {any} */ (e)?.status !== 422) failed(e);
      throw e;
    }
  });
  if (state === null && taken) {
    return html`
      <${AuthCard} title="Choose Another Username" guide="signup-confirm"
        sub="Your email is confirmed; the username you asked for is taken.">
        <form onSubmit=${(/** @type {Event} */ e) => {
          e.preventDefault();
          save.run().catch(() => {});
        }}>
          <${Field} label="Username" error=${errAt(save.error, 'username')}>
            <${Input} value=${username} onInput=${setUsername} autocomplete="username" required />
            </${Field}>
            <${FormError} error=${save.error} shown=${['username']} />
            <button class="btn primary" style=${{ width: '100%', justifyContent: 'center' }}
              disabled=${save.busy}>Send the Request</button>
            </form>
            </${AuthCard}>
    `;
  }
  if (state === null) return null;
  return html`
    <${AuthCard} title=${state ? 'Waiting for Approval' : 'This Link Has Expired'}
      guide="signup-confirm" sub=${state
        ? `Thanks, ${state.displayName}: your email is confirmed. An admin of ${state.household} now approves or rejects your request, and you'll get an email either way.`
        : 'Ask for an account again from the sign-in screen.'}>
        <a class="btn" href="/ui/signin">Back to Sign In</a></${AuthCard}>
  `;
}
