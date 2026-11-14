// An invitation's link (requirements S10.1.3): the invited person chooses their password.
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useSubmit } from '../app/hooks.js';
import { setSession } from '../store/session.js';
import { AuthCard, tokenFromHash } from '../components/auth.js';
import { errAt, Field, FormError, Input } from '../kit/fields.js';

export default function Welcome() {
  const token = tokenFromHash();
  const [who, setWho] = useState(/** @type {any} */ (null));
  const [bad, setBad] = useState(false);
  const [password, setPassword] = useState('');
  useEffect(() => {
    api.post('/invitations/lookup', { token }).then(setWho, () => setBad(true));
  }, [token]);
  const accept = useSubmit(async () => {
    setSession(await api.post('/invitations/accept', { token, password }));
    location.replace('/ui/');
  });
  if (bad) {
    return html`
      <${AuthCard} title="This Link Has Expired" guide="welcome"
        sub="An invitation works once, for 7 days. Ask an admin to send a new one."><a href="/ui/">Sign in</a></${AuthCard}>
    `;
  }
  if (!who) return null;
  return html`
    <${AuthCard} title=${`Welcome, ${who.displayName}`} guide="welcome"
      sub=${`You're invited to ${who.household}'s MoolaKata. Your username is ${who.username}.`}>
      <form onSubmit=${(/** @type {Event} */ e) => {
        e.preventDefault();
        accept.run().catch(() => {});
      }}>
        <input type="text" hidden autocomplete="username" value=${who.username} />
        <${Field} label="Choose a password" id="password" error=${errAt(accept.error, 'password')}
          hint="At least 12 characters; not a common password.">
          <${Input} type="password"
            value=${password} onInput=${setPassword} autocomplete="new-password" required />
          </${Field}>
          <${FormError} error=${accept.error} shown=${['password']} />
          <button class="btn primary" style=${{ width: '100%', justifyContent: 'center' }}
            disabled=${accept.busy}>Join</button>
          </form>
          </${AuthCard}>
  `;
}
