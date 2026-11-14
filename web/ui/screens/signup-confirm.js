// Confirming the email of a sign-up request (requirements S10.1.4): the request then waits for
// an admin, who approves or rejects it; an email says which.
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { AuthCard, tokenFromHash } from '../components/auth.js';

export default function SignupConfirm() {
  const [state, setState] = useState(/** @type {any} */ (null));
  useEffect(() => {
    api.post('/signup/confirm', { token: tokenFromHash() }).then(
      (r) => setState(r),
      () => setState(false),
    );
  }, []);
  if (state === null) return null;
  return html`
    <${AuthCard} title=${state ? 'Waiting for Approval' : 'This Link Has Expired'}
      guide="signup-confirm" sub=${state
        ? `Thanks, ${state.displayName}: your email is confirmed. An admin of ${state.household} now approves or rejects your request, and you'll get an email either way.`
        : 'A confirmation link works once, for a day. Ask for an account again from the sign-in screen.'}>
        <a class="btn" href="/ui/signin">Back to Sign In</a></${AuthCard}>
  `;
}
