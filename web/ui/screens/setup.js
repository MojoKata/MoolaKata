// The first admin's account, the welcome's last step once the key is made: name, sex, email
// address and password, then signed in as `admin` (requirements S10.1.2). An admin made before
// the welcome, with the published password, reaches the same form at its first sign-in.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useSubmit } from '../app/hooks.js';
import { ended, session, setSession } from '../store/session.js';
import { AuthCard } from '../components/auth.js';
import { errAt, Field, FormError, Input, Select } from '../kit/fields.js';

export default function Setup() {
  const [displayName, setName] = useState('');
  const [sex, setSex] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const first = !session.value; // no session: the welcome's first admin
  const save = useSubmit(async () => {
    if (first) {
      setSession(await api.post('/welcome/admin', { displayName, sex, email, password }));
      ended.value = '';
      return;
    }
    setSession(
      await api.post('/session/setup', {
        password,
        email,
        displayName: displayName || null,
        sex: sex || null,
      }),
    );
  });
  return html`
    <${AuthCard} title="Set Up the Admin Account" guide="setup"
      sub=${first
        ? html`
          The key is made and MoolaKata is open. Now your account: you'll sign in as <b
          >admin</b>.
        `
        : "This server is new. Choose the admin's password and email before anything else."}>
      <form onSubmit=${(/** @type {Event} */ e) => {
        e.preventDefault();
        save.run().catch(() => {});
      }}>
        <${Field} label="Your name" hint="Shown to the people you share with."
          error=${errAt(save.error, 'displayName')}>
          <${Input}
            value=${displayName} onInput=${setName} autocomplete="name" required=${first} />
          </${Field}>
          <${Field} label="Sex" error=${errAt(save.error, 'sex')}>
            <${Select} value=${sex} onChange=${setSex} required=${first}
              options=${[
                ['', 'Choose…'],
                ['female', 'Female'],
                ['male', 'Male'],
              ]} />
            </${Field}>
            <${Field} label="Email address" error=${errAt(save.error, 'email')}>
              <${Input} type="email"
                value=${email} onInput=${setEmail} autocomplete="email" required />
              </${Field}>
              <${Field} label="New password" id="password" error=${errAt(save.error, 'password')}
                hint="At least 12 characters, and not a common password.">
                <${Input} type="password" value=${password} onInput=${setPassword}
                  autocomplete="new-password" required />
                </${Field}>
                <${FormError} error=${save.error} shown=${['email', 'password']} />
                <button class="btn primary" style=${{ width: '100%', justifyContent: 'center' }}
                  disabled=${save.busy}>Save and Continue</button>
                </form>
                </${AuthCard}>
  `;
}
