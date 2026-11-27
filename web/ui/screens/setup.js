// The first admin's account, once the key is made: name, sex, email address and password,
// then signed in as `admin` (requirements S10.1.2), and the welcome's last step, the price
// sources that need no key, each off until the admin turns it on (S12.14.1, R3.5). An admin
// made before the welcome, with the published password, reaches the same form at its first
// sign-in.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useSubmit } from '../app/hooks.js';
import { ended, session, setSession } from '../store/session.js';
import { AuthCard } from '../components/auth.js';
import { saveNow } from '../components/draft-form.js';
import { SrcRec } from '../components/price-sources.js';
import { errAt, Field, FormError, Input, Select, SwitchRow } from '../kit/fields.js';
import { Failed, Loading } from '../kit/bits.js';

const WIDE = { width: '100%', justifyContent: 'center' };

export default function Setup() {
  const [displayName, setName] = useState('');
  const [sex, setSex] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  // The first admin, signed in: the session is taken once the price sources are chosen.
  const [made, setMade] = useState(/** @type {any} */ (null));
  const first = !session.value; // no session: the welcome's first admin
  const save = useSubmit(async () => {
    if (first) {
      setMade(await api.post('/welcome/admin', { displayName, sex, email, password }));
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
  if (made) {
    return html`<${PriceSources} done=${() => {
      setSession(made);
      ended.value = '';
    }} />`;
  }
  return html`
    <${AuthCard} title="Set Up the Admin Account" guide="setup"
      sub=${first
        ? html`
          The key is made and MoolaKata is open. Now your account: you'll sign in as <b
          >admin</b>.
        `
        : null}>
      <form onSubmit=${(/** @type {Event} */ e) => {
        e.preventDefault();
        save.run().catch(() => {});
      }}>
        <${Field} label="Your name" error=${errAt(save.error, 'displayName')}>
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
              <${Field} label="New password" id="password" error=${errAt(save.error, 'password')}>
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

/** The price sources that need no key, each off with a switch and the hosts it calls; the
 * ones turned on are added in one save (S12.14.1). Skipped, they wait in Settings › Prices.
 * @param {{ done: () => void }} p */
function PriceSources({ done }) {
  const res = useApi('/price-sources');
  const [on, setOn] = useState(/** @type {string[]} */ ([]));
  const go = useSubmit(async () => {
    if (on.length) await saveNow((d) => on.forEach((name) => void d.add(SrcRec, { name })));
    done();
  });
  const v = /** @type {any} */ (res.data);
  const keyless = v
    ? v.available.filter((/** @type {any} */ s) => s.fetches && !s.needsKey && s.hosts.length)
    : [];
  return html`
    <${AuthCard} title="Price Sources" guide="setup-prices">
      ${res.error
        ? html`<${Failed} error=${res.error} />`
        : !v
        ? html`<${Loading} />`
        : keyless.map((
          /** @type {any} */ s,
        ) =>
          html`
            <${SwitchRow} label=${s.label} hint=${s.hosts.join(', ')} on=${on.includes(s.name)}
              onChange=${(/** @type {boolean} */ x) =>
                setOn(x ? [...on, s.name] : on.filter((n) => n !== s.name))} />
          `
        )}
      <${FormError} error=${go.error} />
      <button type="button" class="btn primary mt" style=${WIDE} disabled=${go.busy || !v}
        onClick=${() => go.run().catch(() => {})}>Continue</button>
      </${AuthCard}>
  `;
}
