// Profile › Connections and an account's sync (requirements S18.6, S18.7): a user's own
// sign-ins at institutions, kept by the MoolaKata Connector. Credentials typed here are sealed
// in this browser to the connector's key before anything is sent: MoolaKata can't read them.
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { withReauth } from './reauth.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { canSeal, seal, sealingKeyIsSigned } from '../app/sealed.js';
import { Dialog, openDialog } from './dialog.js';
import { useDialogGuide } from './help.js';
import { errAt, Field, FormError, Input, Select, SwitchRow } from './fields.js';
import { Failed, Loading } from './bits.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';
import { connectionState, DRIVERS } from './connector.js';
import { Record } from '../app/draft.js';
import { saveNow } from './draft-form.js';
import { FIELDS } from '../api/fields.js';

const DRIVER_OPTIONS = /** @type {[string, string][]} */ ([
  ['schwab', 'Schwab'],
  ['ofx-direct', 'OFX Direct Connect (a bank or credit union)'],
]);

/** @param {string} url */
function hostOf(url) {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return null;
  }
}

/** @param {any} c */
function accountsOf(c) {
  return c.institutionAccounts.map((/** @type {any} */ x) =>
    `${x.name}${x.last4 ? ` ••${x.last4}` : ''}`
  );
}

export function Connections() {
  const info = useApi('/connector');
  const res = useList('/profile/connections', {}, ['task']);
  const rows = /** @type {any[]} */ (res.data);
  const paired = /** @type {any} */ (info.data)?.paired;
  const [armed, setArmed] = useState(/** @type {string | null} */ (null));
  const remove = useSubmit(async (/** @type {any} */ c) => {
    await saveNow((d) => d.remove(d.load(ConnRec, c)));
    toast(`${c.label}: removed; its accounts' sync is off`);
    setArmed(null);
    res.reload();
  });
  const make = () =>
    openDialog(ConnectionDialog, {}).then((made) => {
      if (made) res.reload();
    });
  const credentials = (/** @type {any} */ c) =>
    openDialog(ConnectionDialog, { connection: c }).then((x) => x && res.reload());
  return html`
    <div class="card" id="connections">
      <h3 data-help="connections">Connections<span class="spacer"></span>${paired
        ? html`<button class="btn sm" onClick=${make}><${Icon} name="plus" /> New
            connection</button>`
        : null}</h3>
      <p class="small dim" style=${{ marginTop: '-6px' }}>Your sign-ins at institutions, kept by
        the MoolaKata Connector, never by MoolaKata.</p>
      ${res.error
        ? html`<${Failed} error=${res.error} />`
        : !rows || !info.data
        ? html`<${Loading} lines=${2} />`
        : !paired
        ? html`<p class="small dim">No connector is paired with this server. An admin pairs one
            under Settings › Connector.</p>`
        : !rows.length
        ? html`<p class="small dim">None yet.</p>`
        : rows.map((c) =>
          html`
            <div
              class="list-item"><div class="grow"><b>${c
                .label}</b><div class="small dim">${DRIVERS[c.driver] ||
                c.driver} driver${c.institutionAccounts.length
                ? ` · ${accountsOf(c).join(', ')}`
                : ''}${c.accounts.length
                ? ` · keeps ${c.accounts.map((/** @type {any} */ a) => a.name).join(', ')}`
                : ''}</div>${c.credentialWaiting
                ? html`<div class="small dim">credentials sealed, waiting for the connector</div>`
                : null}</div>${connectionState(c)}
              <button class="btn sm" onClick=${() =>
                credentials(c)}>${c.state === 'needs-sign-in' || c.signInAddress
                ? 'Sign in again'
                : 'Change credentials'}</button>
              <button class="btn sm danger" disabled=${remove.busy}
                onClick=${() =>
                  armed === c.id ? remove.run(c).catch(() => {}) : setArmed(c.id)}>${armed === c.id
                  ? 'Click again to remove'
                  : 'Remove'}</button></div>
          `
        )}
    </div>
  `;
}

/** A Connection (S18.6), as a draft makes it or takes it away. */
class ConnRec extends Record {
  /** @override */
  static prefix = 'Conn';
  /** @override */
  static fields = FIELDS.ConnectionRecord;
}

/**
 * New connection, or new credentials for one (S18.7). What is typed is sealed here to the
 * connector's key; or an admin types it on the connector's host. The connection is made with
 * a draft's save, so a seal that fails after it leaves it made, to seal again.
 * @param {{ close: (v?: any) => void, connection?: any }} p
 */
export function ConnectionDialog({ close, connection }) {
  useDialogGuide('dialog-connection');
  const info = useApi('/connector');
  const existing = connection || null;
  const [f, setF] = useState({
    driver: existing?.driver || 'schwab',
    label: existing?.label || '',
    url: '',
    org: '',
    fid: '',
    accountType: 'CHECKING',
    accountId: '',
    bankId: '',
    appKey: '',
    appSecret: '',
    how: 'sealed',
    username: '',
    password: '',
    landed: '',
  });
  const [sealable, setSealable] = useState(/** @type {boolean | null} */ (null));
  useEffect(() => {
    canSeal().then(setSealable);
  }, []);
  const [made, setMade] = useState(/** @type {any} */ (null));
  const [start] = useState(() => JSON.stringify(f));
  const set = (/** @type {string} */ k) => (/** @type {any} */ x) => setF({ ...f, [k]: x });
  const save = useSubmit(async () => {
    const key = /** @type {any} */ (info.data)?.sealingKey;
    let c = made?.connection || existing;
    if (!c) {
      // The connection is a record, made with the draft's save; its sign-in never is one.
      const settings = f.driver === 'ofx-direct'
        ? {
          url: f.url,
          org: f.org,
          fid: f.fid,
          accountType: f.accountType,
          accountId: f.accountId,
          bankId: f.bankId,
        }
        : { appKey: f.appKey };
      const out = await saveNow((d) => {
        d.add(ConnRec, { driver: f.driver, label: f.label, settings });
      });
      c = out[0].record;
      setMade({ connection: c });
    }
    if (f.how === 'host') {
      setMade({ connection: c, command: command(c) });
      return;
    }
    // The box holds the host the credentials are for and when they were sealed, so the
    // connector refuses one for another server or older than what it holds (protocol §4.3).
    const credentials = f.driver === 'schwab'
      ? { appSecret: f.appSecret, landed: f.landed }
      : { username: f.username, password: f.password };
    const host = f.driver === 'ofx-direct' ? hostOf(c.settings?.url || f.url) : null;
    const plain = JSON.stringify({ credentials, host, sealedAt: Date.now() });
    const v = /** @type {any} */ (info.data);
    if (!(await sealingKeyIsSigned(key, v?.identityKey, v?.sealingSignature))) {
      throw new Error(
        "The connector's sealing key isn't signed by the key an admin confirmed: nothing was sent. Pair the connector again.",
      );
    }
    const box = await seal(plain, key, c.id);
    await withReauth(() => api.post(`/profile/connections/${c.id}/credential`, { sealed: box }));
    toast(`${c.label}: sealed for the connector`);
    close(c);
  });
  const e = save.error;
  const v = /** @type {any} */ (info.data);
  if (!v) {
    return html`
      <${Dialog} title="Connection" close=${close}>
        <${Loading} />
        </${Dialog}>
    `;
  }
  const sealedOk = sealable !== false;
  if (made && f.how === 'host') {
    return html`
      <${Dialog} title=${existing ? 'Change credentials' : 'New connection'} close=${close}
        onSubmit=${() => close(made.connection)}
        footer=${html`<button class="btn primary">Done</button>`}>
        <p class="small dim" style=${{ marginTop: 0 }}>An admin runs this on the connector's
          host and types the credentials there. MoolaKata never handles them.</p>
        <div class="field"
          data-help="connect-command"><code class="mono" style=${{
            display: 'block',
            padding: '10px 12px',
            background: 'var(--bg-3)',
            borderRadius: '8px',
            wordBreak: 'break-all',
          }}>${made.command}</code></div>
        </${Dialog}>
    `;
  }
  return html`
    <${Dialog} title=${existing ? `${existing.label}: credentials` : 'New connection'}
      close=${() => close(made?.connection)} onSubmit=${() => save.run().catch(() => {})}
      changed=${() => JSON.stringify(f) !== start}
      note=${v.fingerprint ? `Sealed with the connector's key ${v.fingerprint}.` : ''}
      footer=${html`<button class="btn primary" disabled=${save.busy}>${
        f.how === 'host' ? 'Show the command' : 'Seal and send'
      }</button>`}>
      <p class="small dim" style=${{ marginTop: 0 }}>A sign-in at one institution, kept by the
        MoolaKata Connector. What you type here is encrypted in your browser for the connector
        before it is sent: MoolaKata can't read it.</p>
      ${v.paired && !v.confirmed
        ? html`
          <div class="notice">
            <${Icon} name="alert" />
            <div>An admin has not yet confirmed
                      that the paired connector is the household's own (Settings › Connector). Until then
                      no sign-in is sealed for it.</div>
          </div>
        `
        : null}
      ${existing ? null : html`
        <div class="row">
          <${Field} label="Institution" id="driver" error=${errAt(e, 'driver')}>
            <${Select} value=${f.driver} onChange=${set('driver')} options=${DRIVER_OPTIONS} />
            </${Field}>
            <${Field} label="Connection name" id="label" error=${errAt(e, 'label')}>
              <${Input} value=${f.label} onInput=${set('label')} placeholder="Schwab login"
                required />
              </${Field}>
              </div>
        ${f.driver === 'ofx-direct'
          ? html`
            <${Field} label="OFX server address" id="ofx-url" error=${errAt(e, 'settings.url')}
              hint="From the institution, or ofxhome.com. The sign-in is bound to this address: changing it later asks for the sign-in again.">
              <${Input} value=${f.url} onInput=${set('url')} placeholder="https://ofx.example.com/"
                required />
              </${Field}>
              <div class="row">
                <${Field} label="ORG" id="ofx-org" error=${errAt(e, 'settings.org')}>
                  <${Input} value=${f.org} onInput=${set('org')} required />
                  </${Field}>
                  <${Field} label="FID" id="ofx-fid" error=${errAt(e, 'settings.fid')}>
                    <${Input} value=${f.fid} onInput=${set('fid')} required />
                    </${Field}>
                    </div>
                    <${Field} label="Routing number" id="ofx-bank-id" error=${errAt(
                      e,
                      'settings.bankId',
                    )}
                      hint="For a bank account; a card or an investment account has none.">
                      <${Input} value=${f.bankId} onInput=${set('bankId')} />
                      </${Field}>
                      <div class="row">
                        <${Field} label="Account type" id="ofx-account-type" error=${errAt(
                          e,
                          'settings.accountType',
                        )}>
                          <${Select} value=${f.accountType} onChange=${set('accountType')}
                            options=${[['CHECKING', 'Checking'], ['SAVINGS', 'Savings'], [
                              'CREDITCARD',
                              'Credit card',
                            ], ['INVESTMENT', 'Investment']]} />
                          </${Field}>
                          <${Field} label="Account number" id="ofx-account-id" error=${errAt(
                            e,
                            'settings.accountId',
                          )}>
                            <${Input} value=${f.accountId} onInput=${set('accountId')} required />
                            </${Field}>
                            </div>
          `
          : html`
            <${Field} label="App key" id="schwab-app-key" error=${errAt(e, 'settings.appKey')}
              hint="From your Schwab developer account's app. Not a secret: the sign-in is.">
              <${Input} value=${f.appKey} onInput=${set('appKey')} required />
              </${Field}>
          `}
      `}
      ${html`
        <${Field} label="How you sign in" id="how-you-sign-in">
          <${Select} value=${f.how} onChange=${set('how')} options=${[
            ['sealed', 'Here, sealed for the connector'],
            ['host', "An admin types it on the connector's host"],
          ]} />
          </${Field}>
        ${f.how === 'host' ? null : !sealedOk
          ? html`
            <div class="notice">
              <${Icon} name="alert" />
              <div>This browser can't seal
                          credentials (no X25519 in WebCrypto). Choose the stricter way: an admin types them
                          on the connector's host.</div>
            </div>
          `
          : f.driver === 'schwab'
          ? html`
            <div class="notice">
              <${Icon} name="info" />
              <div>Schwab signs you in on its own page.
              ${existing?.signInAddress
                ? html`<a href=${existing.signInAddress} target="_blank" rel="noopener">Open
                    Schwab's sign-in at ${existing.signInHost}</a>, sign in, then paste the address you land on below.`
                : 'Once the connector has the app key it reports the sign-in address here; open it, sign in, then paste the address you land on below.'} It lasts seven
              days; you'll be asked again each week.</div>
            </div>
            <${Field} label="App secret" id="schwab-app-secret"
              hint="Your Schwab app's secret, sealed for the connector with the sign-in.">
              <${Input} type="password" value=${f.appSecret} onInput=${set('appSecret')}
                autocomplete="off" />
              </${Field}>
              <${Field} label="The address you landed on" id="landed" error=${errAt(e, 'sealed')}>
                <${Input} value=${f.landed} onInput=${set('landed')}
                  placeholder="https://127.0.0.1/?code=…" />
                </${Field}>
          `
          : html`
            <div class="row">
              <${Field} label="Username" id="username">
                <${Input} value=${f.username} onInput=${set('username')} autocomplete="off" />
                </${Field}>
                <${Field} label="Password" id="password" error=${errAt(e, 'sealed')}>
                  <${Input} type="password" value=${f.password} onInput=${set('password')}
                    autocomplete="off" />
                  </${Field}>
                  </div>
          `}
      `}
      <${FormError} error=${e} shown=${['driver', 'label', 'sealed']} />
    </${Dialog}>
  `;
}

/** @param {any} c */
function command(c) {
  return `docker compose exec connector moolakata-connector connect ${c.id}`;
}

/**
 * Sync using MoolaKata Connector (S18.6.2), on an account's Settings tab, for its owner: which
 * Connection keeps it current and which of its institution accounts this is, fields of the
 * account's draft.
 * @param {{ rec: import('../app/draft.js').Record }} p
 */
export function SyncCard({ rec }) {
  const info = useApi('/connector');
  const res = useList('/profile/connections', {}, ['task']);
  const rows = /** @type {any[]} */ (res.data) || [];
  const [on, setOn] = useState(rec.get('connectionId') != null);
  const cid = rec.get('connectionId') || '';
  const which = rec.shown('syncAccount');
  const paired = /** @type {any} */ (info.data)?.paired;
  if (!info.data) return null;
  if (!paired) return null;
  const chosen = rows.find((c) => c.id === cid);
  const options = [
    ['', 'Choose…'],
    ...rows.map((c) => [c.id, c.label]),
    ['new', 'New connection…'],
  ];
  const pick = (/** @type {string} */ v) => {
    if (v === 'new') {
      openDialog(ConnectionDialog, {}).then((made) => {
        if (made) {
          res.reload();
          rec.set('connectionId', made.id);
        }
      });
      return;
    }
    rec.input('connectionId', v);
    rec.set('syncAccount', null);
  };
  const turn = (/** @type {boolean} */ v) => {
    setOn(v);
    if (!v) {
      rec.set('connectionId', null);
      rec.set('syncAccount', null);
    }
  };
  const found = chosen ? accountsOf(chosen) : [];
  return html`
    <div style=${{ marginTop: '12px' }}>
      <${SwitchRow} label="Sync using MoolaKata Connector" on=${on} onChange=${turn}
        hint=${chosen
          ? `${chosen.label}${which ? ` · ${which}` : ''}`
          : 'Fetched from the institution by the connector; you keep the sign-in.'} />
      ${on
        ? html`
          <div class="row">
            <${Field} label="Connection" id="connection" error=${rec.error('connectionId')}>
              <${Select} value=${cid} onChange=${pick} options=${options} />
              </${Field}>
              <${Field} label="Institution account" id="institution-account"
                error=${rec.error('syncAccount')}
                hint=${found.length ? '' : 'What the driver found on its first run, or type it.'}>
              ${found.length
                ? html`
                  <${Select} value=${which} onChange=${(/** @type {string} */ v) =>
                    rec.input('syncAccount', v)}
                    options=${[['', 'Choose…'], ...found.map((x) => [x, x])]} />
                `
                : html`
                  <${Input} value=${which} onInput=${(/** @type {string} */ v) =>
                    rec.input('syncAccount', v)} placeholder="Individual ••4417" />
                `}
            </${Field}>
          </div>
        `
        : null}
    </div>
  `;
}
