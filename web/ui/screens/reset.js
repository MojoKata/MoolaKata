// A password-reset link (requirements S10.1.5): choose a new password; every session ends.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useSubmit } from '../app/hooks.js';
import { AuthCard, tokenFromHash } from '../components/auth.js';
import { errAt, Field, FormError, Input } from '../kit/fields.js';

export default function Reset() {
  const token = tokenFromHash();
  const [password, setPassword] = useState('');
  const [done, setDone] = useState(false);
  const save = useSubmit(async () => {
    await api.post('/password-reset/confirm', { token, password });
    setDone(true);
  });
  if (done) {
    return html`
      <${AuthCard} title="Password Changed" guide="reset"
        sub="Every session was signed out. Sign in with the new password."><a class="btn primary" href="/ui/">Sign in</a></${AuthCard}>
    `;
  }
  return html`
    <${AuthCard} title="Choose a New Password" guide="reset">
      <form onSubmit=${(/** @type {Event} */ e) => {
        e.preventDefault();
        save.run().catch(() => {});
      }}>
        <${Field} label="New password" id="password" error=${errAt(save.error, 'password')}>
          <${Input} type="password"
            value=${password} onInput=${setPassword} autocomplete="new-password" required />
          </${Field}>
          <${FormError} error=${save.error} shown=${['password']} />
          <button class="btn primary" style=${{ width: '100%', justifyContent: 'center' }}
            disabled=${save.busy}>Change the Password</button>
          </form>
          </${AuthCard}>
  `;
}
