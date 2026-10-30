// Settings, for admins (requirements S16): one screen with its sections listed on the left,
// General first. Each section saves its own keys; a refusal shows at its field.
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { dev } from '../app/config.js';
import { api } from '../api/client.js';
import { useApi, useSubmit } from '../app/hooks.js';
import { ago, date, day, moment } from '../app/format.js';
import { useTitle } from '../components/frame.js';
import { useDialogGuide, useGuide } from '../components/help.js';
import { Failed, Loading } from '../components/bits.js';
import { Icon } from '../components/icon.js';
import { Dialog, openDialog } from '../components/dialog.js';
import { errAt, Field, FormError, Input, Select, Switch, SwitchRow } from '../components/fields.js';
import { toast } from '../components/toast.js';
import { awaitRestart, loadSession } from '../store/session.js';
import { disconnect } from '../app/stream.js';
import { LinksSection } from '../components/links.js';
import { ConnectorSection } from '../components/connector.js';
import { withReauth } from '../components/reauth.js';
import { StorageSection } from '../components/storage.js';
import { DraftDialog, DraftForm, saveNow, useDraft } from '../components/draft-form.js';
import { Record as Rec } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { useSettingsDraft } from '../components/settings-draft.js';
import { confirmAction } from '../components/confirm.js';

const SECTIONS = /** @type {[string, string][]} */ ([
  ['general', 'General'],
  ['email', 'Email (SMTP)'],
  ['sessions', 'Sign-in and sessions'],
  ['signup', 'Sign-up'],
  ['passwords', 'Passwords'],
  ['prices', 'Prices'],
  ['bitcoin', 'Bitcoin'],
  ['links', 'Linked servers'],
  ['connector', 'Connector'],
  ['imports', 'Imports'],
  ['receipts', 'Receipts'],
  ['tax-tables', 'Tax tables'],
  ['backups', 'Backups'],
  ['storage', 'Storage'],
  ['keys', 'Key storage'],
  ['network', 'Network'],
  ['alerts', 'Alerts'],
]);

/** @param {{ section?: string }} p */
export default function Settings({ section }) {
  const current = SECTIONS.some(([k]) => k === section)
    ? /** @type {string} */ (section)
    : 'general';
  const label = SECTIONS.find(([k]) => k === current)?.[1] || '';
  useTitle(label, [['Settings', '/ui/settings']]);
  useGuide('settings-' + current);
  return html`
    <div class="settings-layout">
      <nav class="settings-nav" aria-label="Settings">${SECTIONS.map(([k, l]) =>
        html`<a class=${k === current ? 'on' : ''} href=${`/ui/settings/${k}`} aria-current=${
          k === current ? 'page' : undefined
        }>${l}</a>`
      )}</nav>
      <div>${current === 'prices'
        ? html`<${Prices} />`
        : current === 'backups'
        ? html`<${Backups} />`
        : current === 'storage'
        ? html`<${StorageSection} />`
        : current === 'keys'
        ? html`<${Keys} />`
        : current === 'email'
        ? html`<${EmailSection} />`
        : current === 'bitcoin'
        ? html`<${BitcoinSection} />`
        : current === 'links'
        ? html`<${LinksSection} />`
        : current === 'connector'
        ? html`<${ConnectorSection} />`
        : current === 'tax-tables'
        ? html`<${TaxTables} />`
        : html`<${Plain} section=${current} />`}</div>
    </div>
  `;
}

/** Each plain section's keys. */
const KEYS = /** @type {{ [section: string]: string[] }} */ ({
  general: ['serverName', 'householdName', 'householdAvatar', 'publicUrl'],
  sessions: ['sessionIdleHours', 'sessionAbsoluteDays', 'lockoutFailures', 'lockoutMinutes'],
  signup: ['signupEnabled', 'signupDomains'],
  network: ['networkAppRanges', 'networkLinkRanges', 'networkConnectorRanges'],
  receipts: ['receiptMaxMb', 'readReceipts', 'receiptReadJobs'],
  alerts: ['alertSourceHours', 'alertSummaryTime'],
  passwords: ['passwordMinLength'],
  imports: ['importMaxMb', 'readStatements'],
});

/**
 * The sections that are plain settings: a form over their keys, a draft of them saved with
 * the section's Save (S12.15).
 * @param {{ section: string }} p
 */
function Plain({ section }) {
  const res = useApi('/settings');
  const v = /** @type {any} */ (res.data);
  const keys = KEYS[section] || KEYS.imports;
  const fd = useSettingsDraft(v, keys);
  const rec = fd.rec;
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v || !rec) return html`<${Loading} />`;
  /** @type {Record<string, any>} */
  const f = Object.fromEntries(keys.map((k) => [k, rec.get(k)]));
  const setF = (/** @type {Record<string, any>} */ next) => {
    for (const k of keys) if (next[k] !== f[k]) rec.set(k, next[k]);
  };
  const set = (/** @type {string} */ k, num = false) => (/** @type {string} */ x) =>
    rec.set(k, num ? (x === '' ? '' : Number(x)) : x);
  // The refusals at their keys, as errAt reads them.
  const e = { errors: rec.errors };
  const label = SECTIONS.find(([k]) => k === section)?.[1] || 'Imports';
  const form = (/** @type {string[]} */ _keys, /** @type {any} */ body) =>
    html`
      <${DraftForm} f=${fd} class="card content-narrow" where=${`Settings › ${label}`}
        what="These settings" saved=${() => {
          toast('Saved');
          res.reload();
          if (keys.includes('householdName')) loadSession();
        }}>${body}</${DraftForm}>
    `;
  if (section === 'general') {
    const av = f.householdAvatar || { kind: 'initials', initials: '', color: '#3b7a57' };
    return form(
      ['serverName', 'householdName', 'householdAvatar', 'publicUrl'],
      html`
        <h3>General</h3>
        <${Field} label="Server name" error=${errAt(
          e,
          'serverName',
        )} hint="Shown to linked servers.">
          <${Input}
            value=${f.serverName} onInput=${set('serverName')} />
          </${Field}>
          <div
            class="list-item"><span class="grow dim">Server time zone</span>${v
              .serverZone} <span class="small dim">· from the host</span></div>
          <${Field} label="Household name" error=${errAt(e, 'householdName')}
            hint="At the top of the sidebar, and sent to linked servers with the avatar.">
            <${Input} value=${f.householdName}
              onInput=${set('householdName')} />
            </${Field}>
            <div class="row">
              <${Field} label="Household initials" id="household-initials" error=${errAt(
                e,
                'householdAvatar',
              )}>
                <${Input}
                  value=${av.initials || ''} onInput=${(/** @type {string} */ x) =>
                    setF({ ...f, householdAvatar: { ...av, kind: 'initials', initials: x } })} />
                </${Field}>
                <${Field} label="Household colour"
                  id="household-colour"><input class="in" type="color" value=${av.color ||
                    '#3b7a57'}
                  onInput=${(/** @type {any} */ ev) =>
                    setF({
                      ...f,
                      householdAvatar: { ...av, kind: 'initials', color: ev.currentTarget.value },
                    })} /></${Field}></div>
              <${Field} label="Public URL" error=${errAt(e, 'publicUrl')}
                hint="Links in emails are built from it, never from the request."><${Input} value=${f
                  .publicUrl || ''}
                onInput=${set('publicUrl')} placeholder="https://money.example.lan" /></${Field}>
      `,
    );
  }
  if (section === 'sessions') {
    return form(
      ['sessionIdleHours', 'sessionAbsoluteDays', 'lockoutFailures', 'lockoutMinutes'],
      html`
        <h3>Sign-in and sessions</h3>
        <div class="row">
          <${Field} label="Idle timeout (hours)" error=${errAt(e, 'sessionIdleHours')}
            hint="Signed out after this long without using MoolaKata.">
            <${Input} value=${f.sessionIdleHours} onInput=${set(
              'sessionIdleHours',
              true,
            )} inputmode="numeric" />
            </${Field}>
            <${Field} label="Longest session (days)" error=${errAt(e, 'sessionAbsoluteDays')}
              hint="Signed out after this long, used or not.">
              <${Input} value=${f.sessionAbsoluteDays} onInput=${set(
                'sessionAbsoluteDays',
                true,
              )} inputmode="numeric" />
              </${Field}>
              </div>
              <div class="row">
                <${Field} label="Failed sign-ins before a lockout" error=${errAt(
                  e,
                  'lockoutFailures',
                )}>
                  <${Input}
                    value=${f.lockoutFailures} onInput=${set(
                      'lockoutFailures',
                      true,
                    )} inputmode="numeric" />
                  </${Field}>
                  <${Field} label="Lockout (minutes)" error=${errAt(e, 'lockoutMinutes')}>
                    <${Input} value=${f.lockoutMinutes}
                      onInput=${set('lockoutMinutes', true)} inputmode="numeric" />
                    </${Field}>
                    </div>
      `,
    );
  }
  if (section === 'signup') {
    return form(
      ['signupEnabled', 'signupDomains'],
      html`
        <h3>Sign-up</h3>
        <${SwitchRow} label="Sign-up" on=${f.signupEnabled}
          onChange=${(/** @type {boolean} */ x) => setF({ ...f, signupEnabled: x })}
          hint="People can ask for an account from the sign-in screen; an admin approves or rejects each request. It needs email (SMTP) and the public URL." />
        ${errAt(e, 'signupEnabled')
          ? html`<div class="err">${errAt(e, 'signupEnabled')}</div>`
          : null}
        <${Field} label="Allowed email domains" id="signup-domains" error=${errAt(
          e,
          'signupDomains',
        )}
          hint="Optional, separated by commas. Requests from other domains are refused.">
          <${Input} value=${(f.signupDomains || []).join(', ')} placeholder="any domain"
            onInput=${(/** @type {string} */ x) =>
              setF({
                ...f,
                signupDomains: x.split(',').map((d) => d.trim()).filter(Boolean),
              })} />
          </${Field}>
      `,
    );
  }
  if (section === 'network') {
    const ranges = (/** @type {string} */ k) => (f[k] || []).join('\n');
    const setRanges = (/** @type {string} */ k) => (/** @type {string} */ x) =>
      setF({ ...f, [k]: x.split(/[\n,]/).map((r) => r.trim()).filter(Boolean) });
    const area = (/** @type {string} */ k, /** @type {string} */ placeholder) =>
      html`
        <textarea class="in" rows="3" value=${ranges(k)} placeholder=${placeholder}
          onInput=${(/** @type {any} */ ev) => setRanges(k)(ev.currentTarget.value)}></textarea>
      `;
    return form(
      ['networkAppRanges', 'networkLinkRanges', 'networkConnectorRanges'],
      html`
        <h3>Network</h3>
        <p class="small dim" style=${{ marginTop: '-6px' }}>While the server is locked these ranges
          can't be read: the locked screen answers any address that reaches it, and the reverse
          proxy and the host's firewall are what limit it.</p>
        <${Field} label="Allowed to use the app" id="network-app-ranges" error=${errAt(
          e,
          'networkAppRanges',
        )}
          hint="Address ranges that may reach /ui, and /mcp with it, one per line. Empty allows any.">
          ${area('networkAppRanges', 'any address')}
          </${Field}>
          <${Field} label="Allowed to link" id="network-link-ranges" error=${errAt(
            e,
            'networkLinkRanges',
          )}
            hint="Where linked servers call /link from. Empty allows any.">
            ${area('networkLinkRanges', 'any address')}
            </${Field}>
            <${Field} label="Allowed to connect" id="network-connector-ranges" error=${errAt(
              e,
              'networkConnectorRanges',
            )}
              hint="Where the MoolaKata Connector calls /connector from: the LAN and the overlay by default. A connector on a laptop away from home needs its range added.">
              ${area('networkConnectorRanges', 'any address')}
              </${Field}>
              <p class="small dim">/healthz and /demo answer any address.</p>
      `,
    );
  }
  if (section === 'receipts') {
    return html`
      ${form(
        ['receiptMaxMb', 'readReceipts', 'receiptReadJobs'],
        html`
          <h3>Receipts</h3>
          <p class="small dim" style=${{
            marginTop: '-6px',
          }}>Receipts are kept encrypted in the data
            directory, each file once. Backups hold the database alone: the host's own backup of
            the data directory keeps the files.</p>
          <div class="list-item"><span class="grow dim">File types</span>PDF, JPEG, PNG, WebP, HEIC
            <span class="small dim">· checked from the content</span></div>
          <${Field} label="Largest file (MB)" id="receipt-max-mb" error=${errAt(e, 'receiptMaxMb')}>
            <${Input} value=${f.receiptMaxMb} onInput=${set(
              'receiptMaxMb',
              true,
            )} inputmode="numeric" />
            </${Field}>
            <${SwitchRow} label="Read receipts" on=${f.readReceipts}
              onChange=${(/** @type {boolean} */ x) => setF({ ...f, readReceipts: x })}
              hint="The date, total and merchant, read on this server; nothing leaves it. Off for a host too small to run it." />
            <${Field} label="Jobs at a time" id="receipt-read-jobs" error=${errAt(
              e,
              'receiptReadJobs',
            )}
              hint="Each runs in its own process with 2 threads. 1 suits most hosts; more read a batch faster.">
              <${Select} value=${String(f.receiptReadJobs)}
                onChange=${(/** @type {string} */ x) => setF({ ...f, receiptReadJobs: Number(x) })}
                options=${[['1', '1'], ['2', '2'], ['3', '3'], ['4', '4']]} />
              </${Field}>
        `,
      )}
      <${ReadingQueue} />
    `;
  }
  if (section === 'alerts') {
    return form(
      ['alertSourceHours', 'alertSummaryTime'],
      html`
        <h3>Alerts</h3>
        <p class="small dim" style=${{
          marginTop: '-6px',
        }}>Alerts tell people when something needs them.
          Each user chooses in Profile whether they are emailed.</p>
        <${Field} label="Alert when a source has failed for" id="alert-source-hours"
          error=${errAt(e, 'alertSourceHours')}
          hint="Price sources and email. Admins are alerted.">
          <${Select} value=${String(f.alertSourceHours)}
            onChange=${(/** @type {string} */ x) => setF({ ...f, alertSourceHours: Number(x) })}
            options=${[['24', '24 hours'], ['48', '48 hours'], ['72', '72 hours'], [
              '168',
              '1 week',
            ]]} />
          </${Field}>
          <${Field} label="Daily summary at" id="alert-summary-time" error=${errAt(
            e,
            'alertSummaryTime',
          )}
            hint="In each person's time zone, for those who chose the daily summary.">
            <${Input} type="time" value=${f.alertSummaryTime} onInput=${set('alertSummaryTime')} />
            </${Field}>
      `,
    );
  }
  if (section === 'passwords') {
    return form(
      ['passwordMinLength'],
      html`
        <h3>Passwords</h3>
        <${Field} label="Minimum length" error=${errAt(e, 'passwordMinLength')}
          hint="At least 8. The only rule: no character classes, no expiry; the most common passwords are refused.">
          <${Input}
            value=${f.passwordMinLength} onInput=${set(
              'passwordMinLength',
              true,
            )} inputmode="numeric" />
          </${Field}>
      `,
    );
  }
  return form(
    ['importMaxMb', 'readStatements'],
    html`
      <h3>Imports</h3>
      <p class="small dim"
        style=${{
          marginTop: '-6px',
        }}>Accounts are kept current from the files people bring: OFX, QFX and CSV
            downloads, and statements, and by the MoolaKata Connector for accounts whose sync
            is on.</p>
      <div
        class="list-item"><span class="grow dim">File types</span>OFX, QFX, CSV; statements as PDF, JPEG, PNG, WebP, HEIC <span class="small dim">· checked from the content</span></div>
      <${Field} label="Largest file (MB)" error=${errAt(e, 'importMaxMb')}>
        <${Input} value=${f.importMaxMb}
          onInput=${set('importMaxMb', true)} inputmode="numeric" />
        </${Field}>
        <${SwitchRow} label="Read statements" on=${f.readStatements}
          onChange=${(/** @type {boolean} */ x) => setF({ ...f, readStatements: x })}
          hint="A statement's PDF, or a photo of one, read on this server by the receipt reader and checked before it is saved." />
    `,
  );
}

function Prices() {
  const res = useApi('/price-sources', {}, ['prices']);
  const all = useApi('/settings');
  const v = /** @type {any} */ (res.data);
  const fd = useSettingsDraft(all.data, ['priceRefreshTime']);
  const time = fd.rec;
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v || !time) return html`<${Loading} />`;
  // A switch or a Remove saves at once, as a draft of one change (S12.15).
  const change = async (/** @type {any} */ src, /** @type {any} */ body) => {
    try {
      await saveNow((d) => {
        const r = d.load(SrcRec, src);
        for (const [k, x] of Object.entries(body)) r.set(k, x);
      });
      res.reload();
    } catch (e) {
      toast(/** @type {any} */ (e).message);
    }
  };
  const remove = async (/** @type {any} */ src) => {
    const sure = await confirmAction({ title: `Remove ${src.label}?`, yes: 'Yes, remove' });
    if (!sure) return;
    try {
      await saveNow((d) => d.remove(d.load(SrcRec, src)));
      toast(`${src.label} removed`);
      res.reload();
    } catch (e) {
      toast(/** @type {any} */ (e).message);
    }
  };
  return html`<div class="card"><h3>Price sources<span class="spacer"></span><button type="button" class="btn sm"
    onClick=${() =>
    openDialog(AddSource, { sources: v }).then((x) =>
      x && res.reload()
    )}><${Icon} name="plus" /> Add a source</button></h3>
    <p class="small dim" style=${{
    marginTop: '-6px',
  }}>Free, daily closes. For each class, the first enabled source in the order is
      used, and the next one if it fails. Every price shows its source and date.</p>
    ${
    v.sources.length
      ? html`
        <div class="table-wrap">
          <table class="t">
            <caption class="sr-only">Price sources</caption>
            <thead>
              <tr>
                <th>Source</th>
                <th>Serves</th>
                <th>Key</th>
                <th>Last run</th>
                <th class="num">Enabled</th>
                <th></th>
              </tr>
            </thead>
            <tbody>${v.sources.map((/** @type {any} */ src) =>
              html`
                <tr>
                  <td><b>${src.label}</b>${src.name === 'stub'
                    ? html`
                      <span class="pill bad">dev</span>
                    `
                    : null}<div class="small dim">${src.terms}</div></td>
                  <td class="small dim">${src.classes.join(', ')}</td>
                  <td class="small">${!src.needsKey
                    ? html`<span class="dim">none needed</span>`
                    : src.key
                    ? html`
                      <span class="pill ok" data-tip=${`set ${moment(src.key.setAt)}${
                        src.key.setBy ? ' by ' + src.key.setBy : ''
                      }`}><${Icon} name="lock" /> set</span>
                      <button type="button" class="linklike small" onClick=${() =>
                        openDialog(SetKey, { src }).then((x) => x && res.reload())}>change</button>
                    `
                    : html`<button type="button" class="btn sm" onClick=${() =>
                      openDialog(SetKey, { src }).then((x) =>
                        x && res.reload()
                      )}>Set the key</button>`}</td>
                  <td class="small dim">${src.lastRunAt
                    ? ago(src.lastRunAt)
                    : 'not yet'}${src.lastError
                    ? html`<div style=${{ color: 'var(--deny)' }}>${src.lastError}</div>`
                    : null}</td>
                  <td class="num">
                    <${Switch} on=${src.enabled} label=${'Enabled: ' +
                      src.label} help="enabled" id=${'enabled-' +
                      src.name}
                      onChange=${(/** @type {boolean} */ x) => change(src, { enabled: x })} />
                  </td>
                  <td
                    class="num"><button type="button" class="btn sm danger" onClick=${() =>
                      remove(src)}>Remove</button></td>
                </tr>
              `
            )}</tbody>
          </table>
        </div>
      `
      : html`
        <p
          class="small dim">No sources yet: prices are off until one is added. Without them, holdings are valued from
                the brokers' files and the last trade.</p>
      `
  }
    <${DraftForm} f=${fd} class="draft-form mt" where="Settings › Prices"
      what="The refresh time" saved=${() => {
    toast('Saved');
    all.reload();
  }}><div style=${{ maxWidth: '360px' }}><${Field} label="Daily refresh at"
      error=${time.error('priceRefreshTime')}
      hint=${`${v.refreshZone} time, after the US market close.`}><${Input} type="time"
      value=${time.get('priceRefreshTime')} onInput=${(/** @type {string} */ x) =>
    time.set('priceRefreshTime', x)} /></${Field}></div></${DraftForm}>
    <div class="toolbar"><button type="button" class="btn" onClick=${() =>
    api.post('/prices/refresh').then(
      () => toast('Refreshing prices: the header shows when it is done'),
      (e) => toast(e.message),
    )}><${Icon} name="refresh" /> Refresh prices</button></div>
  </div>`;
}

/** A price source (S4.2), as a draft adds, changes or removes it. */
class SrcRec extends Rec {
  /** @override */
  static prefix = 'Src';
  /** @override */
  static fields = FIELDS.SourceRecord;
}

/** @param {{ close: (v?: any) => void, sources: any }} p */
function AddSource({ close, sources }) {
  useDialogGuide('dialog-add-source');
  const added = new Set(sources.sources.map((/** @type {any} */ s) => s.name));
  const options = sources.available.filter((/** @type {any} */ s) => !added.has(s.name));
  const [name, setName] = useState(options[0]?.name || '');
  const chosen = options.find((/** @type {any} */ s) => s.name === name);
  const save = useSubmit(async () => {
    close(await saveNow((d) => void d.add(SrcRec, { name })));
    toast(`${chosen.label} added${chosen.needsKey ? ': set its key to enable it' : ''}`);
  });
  return html`
    <${Dialog} title="Add a price source" close=${close} onSubmit=${() =>
      save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${
        save.busy || !chosen
      }>Add the source</button>`}>
        ${options.length
          ? html`<${Field} label="Source"><${Select} value=${name} onChange=${setName}
      options=${
            options.map((
              /** @type {any} */ s,
            ) => [
              s.name,
              `${s.label} · ${s.classes.join(', ')} · ${s.needsKey ? 'free key' : 'no key'}`,
            ])
          } /></${Field}>
      ${
            chosen
              ? html`<p class="small dim">${chosen.terms}${
                chosen.termsChecked ? ` Terms checked ${date(chosen.termsChecked)}.` : ''
              }
        ${
                chosen.keyUrl
                  ? html`
                    <a href=${chosen
                      .keyUrl} target="_blank" rel="noopener noreferrer">Get a free key</a>
                  `
                  : null
              }</p>`
              : null
          }`
          : html`<p>Every source MoolaKata ships is added.</p>`}
        <${FormError} error=${save.error} />
      </${Dialog}>
  `;
}

/** @param {{ close: (v?: any) => void, src: any }} p */
/** Removing a copy asks for the recovery phrase as well as the password (S16.13). */
/** @param {{ close: (v?: any) => void, c: any }} p */
function RemoveCopy({ close, c }) {
  useDialogGuide('dialog-remove-copy');
  const [words, setWords] = useState('');
  const remove = useSubmit(async () => {
    close(
      await withReauth(() =>
        api.del(`/settings/keys/copies/${encodeURIComponent(c.name)}`, undefined, undefined, {
          phrase: words,
        })
      ),
    );
  });
  return html`
    <${Dialog} title=${`Remove ${c.name}`} close=${close} onSubmit=${() =>
      remove.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${remove.busy}>Remove it</button>`}>
      <p class="small" style=${{ marginTop: 0 }}>It can't be put back. The server's recovery phrase
        says it is you, as well as your password.</p>
      <${Field} label="Recovery phrase" error=${errAt(remove.error, 'phrase')}>
        <${Input} type="password" value=${words} onInput=${setWords} autocomplete="off"
          autocorrect="off" autocapitalize="off" spellcheck=${false} required />
        </${Field}>
        <${FormError} error=${remove.error} shown=${['phrase']} />
        </${Dialog}>
  `;
}

/** Verify key (S15.6.5): a copy of the recovery phrase, checked against the keyring. */
/** @param {{ close: (v?: any) => void }} p */
function VerifyKey({ close }) {
  useDialogGuide('dialog-verify-key');
  const [words, setWords] = useState('');
  const check = useSubmit(async () => {
    close(await api.post('/settings/keys/verify', { phrase: words }));
  });
  return html`
    <${Dialog} title="Verify key" close=${close} onSubmit=${() => check.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${check.busy}>Verify</button>`}>
      <p class="small" style=${{ marginTop: 0 }}>Type the 12 words from one copy of the recovery
        phrase. Nothing changes: MoolaKata checks that they open this server's key, and records the
        check.</p>
      <${Field} label="Recovery phrase" error=${errAt(check.error, 'phrase')}
        hint="Four letters of each word are enough.">
        <${Input} type="password" value=${words} onInput=${setWords} autocomplete="off"
          autocorrect="off" autocapitalize="off" spellcheck=${false} required />
        </${Field}>
        <${FormError} error=${check.error} shown=${['phrase']} />
        </${Dialog}>
  `;
}

function SetKey({ close, src }) {
  useDialogGuide('dialog-source-key');
  const f = useDraft((draft) => {
    draft.load(SrcRec, src);
  }, [src.id]);
  const rec = f.draft?.records[0];
  return html`
    <${DraftDialog} f=${f} title=${`${src.label}'s key`} close=${close} what="This source"
      label="Save the key" done=${`${src.label}'s key is set and the source is on`}>
      ${rec
        ? html`
          <${Field} label="API key" error=${rec.error('apiKey')}
            hint="Stored encrypted and never shown again; Settings shows only that it is set, when and by whom.">
            <${Input} type="password" value=${rec.get('apiKey') || ''} autocomplete="off"
              onInput=${(/** @type {string} */ x) => {
                // A key turns the source on with it.
                if (x) {
                  rec.set('apiKey', x);
                  rec.set('enabled', true);
                } else rec.revertAll();
              }} />
          </${Field}>
          ${src.keyUrl
            ? html`
              <p class="small"><a href=${src.keyUrl} target="_blank" rel="noopener noreferrer"
                >Get a free key</a></p>
            `
            : null}
        `
        : null}
    </${DraftDialog}>
  `;
}

/** An admin's correction of a shipped tax-table figure for a year (S16.11). */
class FigureRec extends Rec {
  /** @override */
  static prefix = 'TaxFg';
  /** @override */
  static fields = FIELDS.FigureRecord;
}

/**
 * Tax tables (S16.11): per year, the figures that ship with MoolaKata, each correctable if the
 * IRS changes it before an update; the shipped value again removes the correction.
 */
function TaxTables() {
  const [year, setYear] = useState(/** @type {number | null} */ (null));
  const res = useApi('/settings/tax-tables', year ? { year } : {});
  const v = /** @type {any} */ (res.data);
  // Each correction is a record of the draft: typing a figure makes or changes one, and the
  // shipped value again removes it (S16.11).
  const fd = useDraft(
    (draft) => {
      for (const r of v?.rows || []) {
        if (!r.figureId) continue;
        draft.load(FigureRec, {
          id: r.figureId,
          version: r.version,
          year: v.year,
          key: r.key,
          value: r.value,
        });
      }
    },
    [v?.year, JSON.stringify((v?.rows || []).map((/** @type {any} */ r) => r.version))],
  );
  const draft = fd.draft;
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v || !draft) return html`<${Loading} />`;
  const recOf = (/** @type {string} */ key) =>
    /** @type {FigureRec[]} */ (draft.records).find((x) => x.get('key') === key);
  const read = (/** @type {any} */ r) => (/** @type {string} */ text) => {
    const x = parse(r, text);
    return [x].flat().some((n) => Number.isNaN(n))
      ? { error: r.kind === 'numbers' ? 'Numbers, separated by commas.' : 'A number.' }
      : { value: { value: x } };
  };
  const shown = (/** @type {any} */ r) => {
    const rec = recOf(r.key);
    return rec && !rec.removed ? rec.typed('value') ?? show(rec.get('value')) : show(r.shipped);
  };
  const type = (/** @type {any} */ r, /** @type {string} */ text) => {
    let rec = recOf(r.key);
    const x = read(r)(text);
    if (x.value && JSON.stringify(x.value.value) === JSON.stringify(r.shipped)) {
      if (rec) draft.remove(rec);
      return;
    }
    if (!rec) rec = draft.add(FigureRec, { year: v.year, key: r.key, value: r.shipped });
    else if (rec.removed) draft.unremove(rec);
    rec.inputAs('value', text, read(r));
  };
  const groups = [...new Set(v.rows.map((/** @type {any} */ r) => r.group))];
  return html`
    <${DraftForm} f=${fd} class="card content-narrow" where="Settings › Tax tables"
      what=${`The ${v.year} tables`} saved=${() => {
        toast('Saved');
        res.reload();
      }}>
      <h3>Tax tables<span class="spacer"></span><select class="in" style=${{ maxWidth: '100px' }}
        aria-label="Year" id="f-year" value=${v.year} disabled=${draft.changed}
        title=${draft.changed ? 'Save or put back the changes first' : undefined}
        onChange=${(/** @type {any} */ ev) => setYear(Number(ev.currentTarget.value))}>${v.years
          .map((/** @type {number} */ y) => html`<option value=${y}>${y}</option>`)}</select></h3>
      <p class="small dim" style=${{
        marginTop: '-6px',
      }}>Shipped with MoolaKata and updated with it.
        Correct a figure here if the IRS changes it before an update.</p>
      ${groups.map((g) =>
        html`
          <h4 class="small dim mt">${g}</h4>
          <table class="t">
            <tbody>${v.rows.filter((/** @type {any} */ r) => r.group === g).map((
              /** @type {any} */ r,
            ) =>
              html`
                <tr>
                  <td>${r.label}${r.corrected
                    ? html`
                      <span class="pill warn" title=${`Shipped: ${
                        show(r.shipped)
                      }`}>corrected</span>
                    `
                    : null}<div class="small dim">${r.source}</div></td>
                  <td class="num"><input class="in num" style=${{
                    maxWidth: '200px',
                  }} data-help="figure"
                                aria-label=${r.label} value=${shown(r)} onInput=${(
                                  /** @type {any} */ ev,
                                ) => type(r, ev.currentTarget.value)} />${recOf(r.key)?.error(
                                    'value',
                                  )
                                  ? html`<div class="err">${recOf(r.key)?.error('value')}</div>`
                                  : null}</td>
                </tr>
              `
            )}</tbody>
          </table>
        `
      )}
    </${DraftForm}>
  `;
}

/** @param {any} value */
function show(value) {
  return Array.isArray(value) ? value.join(', ') : String(value ?? '');
}

/** @param {any} row @param {string} text */
function parse(row, text) {
  if (row.kind === 'numbers') return text.split(',').map((x) => Number(x.trim()));
  return Number(String(text).replace(/[$,%\s]/g, ''));
}

/** The reading queue (S9.8.7): its state, and Re-read all receipts. */
function ReadingQueue() {
  const res = useApi('/settings/receipts', {}, ['receipt']);
  const q = /** @type {any} */ (res.data);
  const reread = useSubmit(async () => {
    await api.post('/settings/receipts/reread');
    toast('Every receipt is queued to be read again');
    res.reload();
  });
  if (!q) return null;
  return html`
    <div class="card content-narrow mt">
      <h3>Reading</h3>
      ${q.fileSandbox === false
        ? html`
          <div class="notice small" role="status" data-help="file-sandbox">
            <${Icon}
              name="info" />
            <div>Reading runs without its file sandbox on this host: it doesn't offer
                    Landlock (Linux 5.13 or later, and a container that allows it), so the reader
                    could open the data directory. It still has no network, and it still runs
                    apart from the server. Admins have an alert while it lasts.</div>
          </div>
        `
        : null}
      <div class="list-item"><span class="grow">Waiting</span>${q.waiting + q.reading}</div>
      <div class="list-item"><span class="grow">Read</span>${q.read}</div>
      <div class="list-item"><span class="grow">Couldn't read</span>${q.failed}</div>
      <div class="list-item"><span class="grow">Last read</span>${q.lastRun
        ? ago(q.lastRun)
        : 'never'}</div>
      <${FormError} error=${reread.error} />
      <p class="small dim">After an update with new models, read them all again: only empty fields, and
        those still holding what was read, are replaced.</p>
      <button type="button" class="btn" disabled=${reread.busy}
        onClick=${() => reread.run().catch(() => {})}>Re-read all receipts</button>
    </div>
  `;
}

/** Email (S16.2): the SMTP server, its password as a secret, a test, and the queue. */
const EMAIL_KEYS = ['smtpHost', 'smtpPort', 'smtpSecurity', 'smtpUsername', 'smtpFrom'];

function EmailSection() {
  const res = useApi('/settings/email', {}, ['task']);
  const s = useApi('/settings');
  const v = /** @type {any} */ (res.data);
  const values = /** @type {any} */ (s.data)?.values;
  // The password is a key of the draft too, written and never read back (S14.4).
  const fd = useSettingsDraft(s.data, [...EMAIL_KEYS, 'smtpPassword']);
  const rec = fd.rec;
  const test = useSubmit(async () => {
    const r = await api.post('/settings/email/test');
    toast(`Test email sent to ${r.to}`);
  });
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v || !rec) return html`<${Loading} />`;
  const f = Object.fromEntries(EMAIL_KEYS.map((k) => [k, rec.get(k) ?? '']));
  // An empty box is no value, as the key was read.
  const set = (/** @type {string} */ k, num = false) => (/** @type {string} */ x) =>
    rec.set(k, num ? (x === '' ? '' : Number(x)) : x || null);
  const password = rec.get('smtpPassword') || '';
  const setPassword = (/** @type {string} */ x) =>
    x ? rec.set('smtpPassword', x) : rec.revert('smtpPassword');
  const e = {
    errors: rec.errors.map((x) => (x.field === 'smtpPassword' ? { ...x, field: 'password' } : x)),
  };
  return html`
    <${DraftForm} f=${fd} class="card content-narrow" where="Settings › Email (SMTP)"
      what="These settings" saved=${() => {
        toast('Saved');
        res.reload();
        s.reload();
      }} extra=${() =>
        html`
          <button type="button" class="btn" disabled=${test.busy ||
            !values.smtpHost}
            onClick=${() => test.run().catch(() => {})}>Send a test email</button>
        `}>
      <h3>Email (SMTP)</h3>
      <p class="small dim" style=${{ marginTop: '-6px' }}>${values.smtpHost
        ? 'Emails go out through this server, waiting in the database, which is encrypted, until sent or until their link expires.'
        : 'Until a host is set, emails are written to the mail folder in the data directory, and listed below for you to pass their links on.'}</p>
      <div class="row">
        <${Field} label="Host" id="smtp-host" error=${errAt(e, 'smtpHost')}
          hint="Changing it asks for your password again and clears the password below: type it again for the new host.">
          <${Input} value=${f.smtpHost} onInput=${set('smtpHost')} placeholder="smtp.example.com" />
          </${Field}>
          <${Field} label="Port" id="smtp-port" error=${errAt(e, 'smtpPort')}>
            <${Input} value=${f.smtpPort} onInput=${set('smtpPort', true)} inputmode="numeric" />
            </${Field}>
            </div>
            <${Field} label="Security" id="smtp-security" error=${errAt(e, 'smtpSecurity')}
              hint="STARTTLS on port 587, TLS on 465. None only for a relay on your own network.">
              <${Select} value=${f.smtpSecurity} onChange=${set('smtpSecurity')}
                options=${[['starttls', 'STARTTLS'], ['tls', 'TLS'], ['none', 'None']]} />
              </${Field}>
              <div class="row">
                <${Field} label="Username" id="smtp-username" error=${errAt(e, 'smtpUsername')}>
                  <${Input} value=${f.smtpUsername} onInput=${set(
                    'smtpUsername',
                  )} autocomplete="off" />
                  </${Field}>
                  <${Field} label="Password" id="smtp-password" error=${errAt(e, 'password')}
                    hint=${v.password
                      ? `Set ${day(v.password.setAt)}${
                        v.password.setBy ? ' by ' + v.password.setBy : ''
                      }. Type a new one to replace it.`
                      : 'Not set.'}>
                    <${Input} type="password" value=${password} onInput=${setPassword}
                      autocomplete="new-password" placeholder=${v.password ? '••••••••' : ''} />
                    </${Field}>
                    </div>
                    <${Field} label="From address" id="smtp-from" error=${errAt(e, 'smtpFrom')}
                      hint="As emails show it, such as MoolaKata <money@example.com>.">
        <${Input} value=${f.smtpFrom} onInput=${set('smtpFrom')} />
      </${Field}>
      ${v.waiting || v.setAside || v.lastError
        ? html`<div class=${'notice small' + (v.lastError ? ' bad' : '')} role="status">
          ${v.waiting} waiting to be sent${
          v.setAside ? `, ${v.setAside} set aside (refused by the SMTP server)` : ''
        }${v.lastError ? html`. Last try ${ago(v.lastRun)}: ${v.lastError}` : ''}</div>`
        : null}
      <${FormError} error=${test.error} />
      ${values.smtpHost ? null : html`<${WrittenEmails} />`}
    </${DraftForm}>
  `;
}

const MEMPOOL = 'https://mempool.space/api';
const BLOCKSTREAM = 'https://blockstream.info/api';
const NODES = /** @type {[string, string][]} */ ([
  ['mempool', 'Public: mempool.space (Esplora)'],
  ['blockstream', 'Public: Blockstream (Esplora)'],
  ['esplora', 'Own node: mempool or Esplora'],
  ['electrum', 'Own node: Electrum server (Fulcrum, electrs)'],
  ['core', 'Own node: Bitcoin Core (RPC, watch-only descriptors)'],
  // Dev mode's made-up history, saved like any source (S17.7).
  ...(dev
    ? /** @type {[string, string][]} */ ([['stub', 'Dev mode: the stub (with --stubs)']])
    : []),
]);

const BITCOIN_KEYS = [
  'bitcoinSource',
  'bitcoinEsploraUrl',
  'bitcoinNodeHost',
  'bitcoinNodePort',
  'bitcoinNodeTls',
  'bitcoinRpcUser',
];

/** Settings › Bitcoin (S16.7, S1.6.2): where self-custody wallets are read. */
function BitcoinSection() {
  const res = useApi('/settings/bitcoin', {}, ['task']);
  const s = useApi('/settings');
  const v = /** @type {any} */ (res.data);
  // The password is a key of the draft too, written and never read back (S14.4).
  const fd = useSettingsDraft(s.data, [...BITCOIN_KEYS, 'bitcoinPassword']);
  const rec = fd.rec;
  const [shown, setShown] = useState(/** @type {string | null} */ (null));
  const test = useSubmit(async () => {
    const r = await api.post('/settings/bitcoin/test');
    toast(r.answer);
    // An Electrum server's certificate, to confirm (S1.6.2.4).
    const m = /certificate SHA-256 ([0-9a-f]{64}) \(not trusted yet/.exec(r.answer);
    setShown(m ? m[1] : null);
  });
  const trust = useSubmit(async (/** @type {string} */ sha256) => {
    await api.post('/settings/bitcoin/certificate', { sha256 });
    setShown(null);
    toast('Certificate trusted');
    res.reload();
  });
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v || !rec) return html`<${Loading} />`;
  // The form's choices, read from the keys and put back into them.
  const url = rec.get('bitcoinEsploraUrl') || MEMPOOL;
  const source = rec.get('bitcoinSource');
  const f = {
    node: source !== 'esplora'
      ? source
      : url === MEMPOOL
      ? 'mempool'
      : url === BLOCKSTREAM
      ? 'blockstream'
      : 'esplora',
    url: url === MEMPOOL || url === BLOCKSTREAM ? '' : url,
    host: rec.get('bitcoinNodeHost') || '',
    port: rec.get('bitcoinNodePort'),
    tls: rec.get('bitcoinNodeTls'),
    rpcUser: rec.get('bitcoinRpcUser') || '',
  };
  const setF = (/** @type {any} */ next) => {
    const esplora = ['mempool', 'blockstream', 'esplora'].includes(next.node);
    rec.set('bitcoinSource', esplora ? 'esplora' : next.node);
    rec.set(
      'bitcoinEsploraUrl',
      next.node === 'mempool'
        ? MEMPOOL
        : next.node === 'blockstream'
        ? BLOCKSTREAM
        : next.node === 'esplora'
        ? next.url
        : rec.get('bitcoinEsploraUrl'),
    );
    rec.set('bitcoinNodeHost', next.host || null);
    rec.set('bitcoinNodePort', next.port);
    rec.set('bitcoinNodeTls', next.tls);
    rec.set('bitcoinRpcUser', next.rpcUser || null);
  };
  const password = rec.get('bitcoinPassword') || '';
  const setPassword = (/** @type {string} */ x) =>
    x ? rec.set('bitcoinPassword', x) : rec.revert('bitcoinPassword');
  const set = (/** @type {string} */ k, num = false) => (/** @type {any} */ x) =>
    setF({ ...f, [k]: num ? (x === '' ? '' : Number(x)) : x });
  const pick = (/** @type {string} */ node) =>
    setF({
      ...f,
      node,
      port: node === 'core' ? 8332 : node === 'electrum' ? 50002 : f.port,
      tls: node === 'core' ? false : node === 'electrum' ? true : f.tls,
    });
  const e = {
    errors: rec.errors.map((
      x,
    ) => (x.field === 'bitcoinPassword' ? { ...x, field: 'password' } : x)),
  };
  const own = ['electrum', 'core'].includes(f.node);
  return html`
    <${DraftForm} f=${fd} class="card content-narrow" where="Settings › Bitcoin"
      what="These settings" saved=${() => {
        toast('Saved');
        res.reload();
        s.reload();
      }} extra=${() =>
        html`<button type="button" class="btn" disabled=${test.busy} onClick=${() =>
          test.run().catch(() => {})}>Test</button>`}>
      <h3>Bitcoin</h3>
      <p class="small dim" style=${{ marginTop: '-6px' }}>Where self-custody wallets' balances and
        history come from. Your own node keeps your addresses private.</p>
      <${Field} label="Explorer or node" error=${errAt(e, 'bitcoinSource')}>
        <${Select} value=${f.node} onChange=${pick} options=${NODES} />
      </${Field}>
      ${f.node === 'esplora'
        ? html`
          <${Field} label="Esplora address" id="esplora-url" error=${errAt(
            e,
            'bitcoinEsploraUrl',
          )}
            hint="Its API, such as http://umbrel.local:3006/api.">
            <${Input} value=${f.url} onInput=${set(
              'url',
            )} placeholder="http://192.168.1.20:3006/api" />
            </${Field}>
        `
        : null}
      ${own
        ? html`
          <div class="row">
            <${Field} label="Node address" id="node-host" error=${errAt(e, 'bitcoinNodeHost')}
              hint="Allowed through the egress guard because it is named here. Changing it clears the node’s stored password.">
              <${Input} value=${f.host} onInput=${set('host')} placeholder="192.168.1.20" />
              </${Field}>
              <${Field} label="Node port" id="node-port" error=${errAt(e, 'bitcoinNodePort')}>
                <${Input} value=${f.port} onInput=${set('port', true)} inputmode="numeric" />
                </${Field}>
                </div>
                <${SwitchRow} label="TLS" hint=${f.node === 'electrum'
                  ? 'Usually on, port 50002; off on port 50001.'
                  : 'On when Core is behind a TLS proxy.'} on=${f.tls} onChange=${set('tls')} />
        `
        : null}
      ${f.node === 'core'
        ? html`
          <div class="row">
            <${Field} label="RPC user" id="rpc-user" error=${errAt(e, 'bitcoinRpcUser')}>
              <${Input} value=${f.rpcUser} onInput=${set('rpcUser')} autocomplete="off" />
              </${Field}>
              <${Field} label="Node password" id="node-password" error=${errAt(e, 'password')}
                hint=${v.password
                  ? `Set ${day(v.password.setAt)}${
                    v.password.setBy ? ' by ' + v.password.setBy : ''
                  }. Type a new one to replace it.`
                  : 'Not set.'}>
                <${Input} type="password" value=${password} onInput=${setPassword}
                  autocomplete="new-password" placeholder=${v.password ? '••••••••' : ''} />
                </${Field}>
                </div>
        `
        : null}
      ${f.node === 'electrum' && f.tls
        ? html`<div class="list-item" data-help="certificate"><span class="grow">Certificate<div
            class="small dim mono" style=${{ wordBreak: 'break-all' }}>${
          v.certificate ? `SHA-256 ${v.certificate}` : 'Not trusted yet: Test shows it, to confirm.'
        }</div></span></div>
          ${
          v.certificateOffered || shown
            ? html`
              <div class="notice warn" role="alert">
                <${Icon} name="lock" />
                <div>${v
                    .certificateOffered
                  ? "The server's certificate changed: it is refused until you confirm the new one."
                  : 'The server presented this certificate. Confirm it only if it is your node.'}
                            <div class="small mono" style=${{ wordBreak: 'break-all' }}>SHA-256 ${v
                              .certificateOffered ||
                              shown}</div><button type="button" class="btn sm mt"
                            disabled=${trust.busy} onClick=${() =>
                              trust.run(v.certificateOffered || shown).catch(() => {})}>Trust this
                            certificate</button></div>
              </div>
            `
            : null
        }`
        : null}
      <div class=${'notice small' + (v.lastError ? ' bad' : '')} role="status" data-help="checked">
        <${Icon} name=${v.lastError ? 'alert' : 'sync'} /><div>${v.wallets} wallet${v.wallets ===
            1
          ? ''
          : 's'} · ${v.lastRun
          ? html`last checked ${ago(v.lastRun)}${v.lastError ? html`: ${v.lastError}` : ''}`
          : 'not checked yet'}. Checked every hour.</div></div>
      <${FormError} error=${test.error} />
      <p class="small dim">Test asks the saved explorer or node for the chain's height: save
        first. Other coins and chains come later.</p>
    </${DraftForm}>
  `;
}

/**
 * *Copies kept* (S16.12): the days of backups kept. Fewer than the backups there are deletes
 * some at the next backup, so it asks for the recovery phrase too, as Remove does (S16.13).
 * @param {{ close: (v?: any) => void, v: any }} p
 */
function CopiesKept({ close, v }) {
  useDialogGuide('dialog-copies-kept');
  const [n, setN] = useState(String(v.copies));
  const [words, setWords] = useState('');
  const days = new Set(v.backups.map((/** @type {any} */ b) => b.name.split('-')[1])).size;
  const fewer = Number(n) < v.copies && Number(n) < days;
  const save = useSubmit(async () => {
    close(
      await withReauth(() =>
        api.post('/settings/backups/copies', {
          copies: Number(n),
          ...(fewer ? { phrase: words } : {}),
        })
      ),
    );
  });
  return html`
    <${Dialog} title="Copies kept" close=${close} onSubmit=${() => save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Save</button>`}>
      <${Field} label="Days of backups kept" error=${errAt(save.error, 'copies')}
        hint="Every backup of each of these most recent days is kept: 3 to 365.">
        <${Input} value=${n} inputmode="numeric" onInput=${setN} required />
        </${Field}>
      ${fewer
        ? html`
          <p class="small">That is fewer than the ${days} days of backups kept, so the next backup
            deletes some, which can't be undone. The server's recovery phrase says it is you, as
            well as your password.</p>
          <${Field} label="Recovery phrase" error=${errAt(save.error, 'phrase')}>
            <${Input} type="password" value=${words} onInput=${setWords} autocomplete="off"
              autocorrect="off" autocapitalize="off" spellcheck=${false} required />
            </${Field}>
        `
        : null}
      <${FormError} error=${save.error} shown=${['copies', 'phrase']} />
      </${Dialog}>
  `;
}

function Backups() {
  const res = useApi('/settings/backups', {}, ['task']);
  const s = useApi('/settings');
  const v = /** @type {any} */ (res.data);
  const fd = useSettingsDraft(s.data, ['backupTime']);
  const rec = fd.rec;
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v || !rec) return html`<${Loading} />`;
  const mb = (/** @type {number} */ n) => (n / 1048576).toFixed(n < 1048576 * 10 ? 1 : 0) + ' MB';
  return html`
    <${DraftForm} f=${fd} class="card content-narrow" where="Settings › Backups"
      what="These settings" saved=${() => {
        toast('Saved');
        s.reload();
        res.reload();
      }} extra=${() =>
        html`
          <button type="button" class="btn" disabled=${v.running}
            onClick=${() =>
              api.post('/settings/backups/run').then(() => {
                toast('Backing up now');
                res.reload(); // shows it running; the live stream says when it ends
              }, (e) => toast(e.message))}><${Icon} name="refresh" /> Back up now</button>
        `}>
      <h3>Backups</h3>
      <div class="row">
        <${Field} label="Time of day" error=${rec.error('backupTime')}>
          <${Input} type="time" value=${rec.get('backupTime')} onInput=${(
            /** @type {string} */ x,
          ) => rec.set('backupTime', x)} />
          </${Field}>
          <div class="field" data-help="copies-kept"><label>Copies kept</label><div class="row"
            style=${{ alignItems: 'center' }}><span>${v.copies} days</span><button type="button"
            class="btn sm" onClick=${() =>
              openDialog(CopiesKept, { v }).then((r) => {
                if (r) {
                  toast('Saved');
                  res.reload();
                  s.reload();
                }
              }, (e) => toast(e.message))}>Change</button></div></div></div>
        <div class=${'notice ' + (v.lastError ? 'bad' : '')}><${Icon} name=${v.lastError
          ? 'alert'
          : 'check'} /><div>${v.lastRun
          ? html`Last backup ${moment(v.lastRun)}${
            v.lastError ? html`: failed (${v.lastError})` : ': encrypted and verified'
          }.`
          : 'No backup yet.'} Directory (set on the host): <code>${v
          .directory}</code>. A backup is the database and its keyring, a coherent copy
          for the host's own backup to pick up; receipt files are never copied, the host
          backs them up with the data directory. Backups open with the recovery phrase.</div></div>
        ${v.backups.length
          ? html`
            <table class="t mt">
              <caption class="sr-only">Backups kept</caption>
              <thead>
                <tr>
                  <th>Made</th>
                  <th class="num">Size</th>
                  <th>Master key</th>
                </tr>
              </thead>
              <tbody>${v.backups.map((/** @type {any} */ b) =>
                html`
                  <tr>
                    <td>${moment(b.made)}</td>
                    <td class="num">${mb(b.bytes)}</td>
                    <td><code>${b.masterKey}</code></td>
                  </tr>
                `
              )}</tbody>
            </table>
          `
          : null}
    </${DraftForm}>
  `;
}

/** How a copy on the host opens (S15.7), in words. @param {string} opens */
function opensWith(opens) {
  return opens === 'current'
    ? 'opens with this phrase'
    : opens === 'phrase'
    ? 'opens with this phrase (an earlier data key)'
    : opens === 'previous'
    ? 'needs a previous phrase'
    : 'its keyring cannot be read';
}

/** The emails written to the mail folder while SMTP is not set up (S16.2). */
function WrittenEmails() {
  const res = useApi('/settings/email/written', {}, ['task']);
  const items = /** @type {any} */ (res.data)?.items || [];
  const open = async (/** @type {any} */ w) => {
    const out = await withReauth(() => api.get(`/settings/email/written/${w.name}`));
    openDialog(WrittenEmailDialog, { w, text: out.text });
  };
  if (!items.length) return null;
  return html`<div class="field" data-help="written-emails"><label>Written to the mail folder</label>
    ${
    items.map((/** @type {any} */ w) =>
      html`
        <div
          class="list-item"><div class="grow">${w.subject}<div class="small dim">to ${w.to} · ${ago(
            w.writtenAt,
          )}</div></div><button type="button" class="btn sm" onClick=${() =>
            open(w).catch((e) => toast(e.message))}>Open</button></div>
      `
    )
  }
    <div class="small dim">Each is removed once its link has expired: a password reset’s after an hour, an invitation’s after a week, the others’ after a day.</div></div>`;
}

/** @param {{ close: (v?: any) => void, w: any, text: string }} p */
function WrittenEmailDialog({ close, w, text }) {
  useDialogGuide('dialog-written-email');
  return html`
    <${Dialog} title=${w.subject} close=${close}>
      <pre class="small" style=${{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>${text}</pre>
      </${Dialog}>
  `;
}

/** The server restarts for a re-encryption (S15.7.2): the locked screen waits for it. The
 * screen is loaded first, since the server stops answering for a moment. */
async function restartNow(/** @type {() => Promise<any>} */ ask) {
  await import('./locked.js');
  const out = await ask();
  disconnect();
  awaitRestart();
  return out;
}

/** Each copy on the host and what a re-encryption does with it (S15.7.2): re-encrypt by
 * default; one under an earlier phrase can only be left or deleted. */
/** @param {{ copies: any[], choices: Record<string, string>, set: (c: Record<string, string>) => void }} p */
function CopyChoices({ copies, choices, set }) {
  if (!copies.length) return null;
  return html`<div class="field" data-help="copies-at-re-encryption"><label>The copies on this host</label>
    ${
    copies.map((/** @type {any} */ c) =>
      html`
        <div class="list-item">
          <div class="grow"><code>${c.name}</code>
            <div class="small dim">${c.what} · ${opensWith(c.opens)}</div></div>
          <span
            style=${{ flex: 'none', width: '180px' }}><${Select} value=${choiceOf(
              c,
              choices,
            )} onChange=${(/** @type {string} */ x) => set({ ...choices, [c.name]: x })} options=${[
              ['reencrypt', 'Re-encrypt'],
              ['delete', 'Delete'],
              ['leave', 'Leave as it is'],
            ]} /></span>
        </div>
      `
    )
  }
    <div class="small dim">A copy that needs a previous phrase can only be left or deleted.</div></div>`;
}

/** @param {any} c @param {Record<string, string>} choices */
const choiceOf = (c, choices) =>
  choices[c.name] ||
  (c.kind !== 'keyring' && (c.opens === 'current' || c.opens === 'phrase') ? 'reencrypt' : 'leave');

/** @param {any[]} copies @param {Record<string, string>} choices */
const chosen = (copies, choices) =>
  Object.fromEntries(copies.map((/** @type {any} */ c) => [c.name, choiceOf(c, choices)]));

/**
 * Rotate (S15.7.1): the current phrase, or a break-glass code from the host for a lost one
 * (S15.5.2), and each copy's choice; then the new phrase, shown once, and three of its words
 * typed back. The server then restarts and unlocks with the new phrase, re-encrypting first.
 * @param {{ close: (v?: any) => void, copies: any[] }} p
 */
function RotateKey({ close, copies }) {
  useDialogGuide('dialog-rotate');
  const [step, setStep] = useState('start'); // start, phrase, check
  const [lost, setLost] = useState(false);
  const [current, setCurrent] = useState('');
  const [code, setCode] = useState('');
  const [choices, setChoices] = useState(/** @type {Record<string, string>} */ ({}));
  const [offer, setOffer] = useState(/** @type {any} */ (null));
  const [typed, setTyped] = useState(/** @type {Record<string, string>} */ ({}));
  const show = useSubmit(async () => {
    setOffer(await api.post('/settings/keys/rotate/phrase'));
    setTyped({});
    setStep('phrase');
  });
  const rotate = useSubmit(async () => {
    close(
      await restartNow(() =>
        withReauth(() =>
          api.post('/settings/keys/rotate', {
            token: offer.token,
            words: typed,
            ...(lost ? { code } : { phrase: current }),
            copies: chosen(copies, choices),
          })
        )
      ),
    );
  });
  const back = /** @type {any} */ (rotate.error)?.code;
  if (step === 'start') {
    return html`
      <${Dialog} title="Rotate the master key" close=${close} onSubmit=${() =>
        show.run().catch(() => {})}
        footer=${html`<button class="btn primary" disabled=${show.busy}>Show the new phrase</button>`}>
        <p class="small" style=${{ marginTop: 0 }}>A new master key and recovery phrase, and with
          them a new data key. MoolaKata then restarts; unlock it with the new phrase, and it
          re-encrypts everything before it serves, the copies below as you choose.</p>
        ${lost
          ? html`
            <${Field} label="Break-glass code" error=${errAt(rotate.error, 'code')}
              hint="From the host: docker compose exec moolakata moolakata keys break-glass. It works once, for 15 minutes.">
              <${Input} value=${code} onInput=${setCode} autocomplete="off" autocapitalize="characters"
                spellcheck=${false} required />
              </${Field}>
          `
          : html`
            <${Field} label="Current recovery phrase" error=${errAt(rotate.error, 'phrase')}
              hint="Four letters of each word are enough.">
              <${Input} type="password" value=${current} onInput=${setCurrent} autocomplete="off"
                autocorrect="off" autocapitalize="off" spellcheck=${false} required />
              </${Field}>
          `}
        <div style=${{ marginBottom: '14px' }}><button type="button" class="btn sm"
          data-help="lost-phrase" onClick=${() => setLost(!lost)}>${lost
            ? 'I have the phrase'
            : 'The phrase is lost'}</button></div>
        <${CopyChoices} copies=${copies} choices=${choices} set=${setChoices} />
        <${FormError} error=${show.error} />
        </${Dialog}>
    `;
  }
  if (step === 'phrase') {
    return html`
      <${Dialog} title="The new recovery phrase" close=${close} onSubmit=${() => setStep('check')}
        footer=${html`<button class="btn primary">I've written them down</button>`}>
        <p class="small" style=${{ marginTop: 0 }}>Write these 12 words on paper, in order. They're
          shown here once.</p>
        <ol class="phrase" aria-label="The new recovery phrase">${offer.words.map((
          /** @type {string} */ w,
        ) => html`<li><b>${w}</b></li>`)}</ol>
        <div class="small dim">Fingerprint <code>${offer.fingerprint}</code> · ${offer
          .serverName} · ${date(offer.made)}</div>
        <div class="notice small mt">
          <${Icon} name="alert" />
          <div>Keep the old phrase too, until
          every copy made under it is gone: the host's own snapshots and backups still need it.</div>
        </div>
        </${Dialog}>
    `;
  }
  return html`
    <${Dialog} title="Check what you wrote" close=${close} onSubmit=${() =>
      rotate.run().catch(() => {})}
      footer=${html`
        <button type="button" class="btn" onClick=${() =>
          setStep(
            back === 'phrase-wrong' || back === 'code-wrong' ? 'start' : 'phrase',
          )}>Back</button><span
          class="spacer"></span><button class="btn primary" disabled=${rotate.busy}>${rotate.busy
            ? 'Rotating…'
            : 'Rotate and restart'}</button>
      `}>
      <p class="small" style=${{ marginTop: 0 }}>Type three of the words from your sheet. Four
        letters of each are enough.</p>
      ${offer.check.map((/** @type {number} */ n) =>
        html`
          <${Field} label=${`Word ${n}`} id=${`rotate-word-${n}`}
            error=${errAt(rotate.error, `word${n}`)}>
            <${Input} value=${typed[n] || ''} onInput=${(/** @type {string} */ v) =>
              setTyped({ ...typed, [n]: v })} autocomplete="off" autocapitalize="none"
              autocorrect="off" spellcheck=${false} required />
            </${Field}>
        `
      )}
      <${FormError} error=${rotate.error} shown=${offer.check.map((/** @type {number} */ n) =>
        `word${n}`
      )} />
      </${Dialog}>
  `;
}

/** The rotation reminder's period (S16.13, S15.8.4): months, or never. */
function ReminderSetting() {
  const s = useApi('/settings');
  const fd = useSettingsDraft(s.data, ['keyReminderMonths']);
  const rec = fd.rec;
  if (!rec) return null;
  const months = Number(rec.get('keyReminderMonths'));
  const options = [0, 6, 12, 18, 24, 36, 48, 60];
  if (!options.includes(months)) options.push(months);
  return html`
    <${DraftForm} f=${fd} class="card mt" where="Settings › Key storage" what="The reminder"
      saved=${() => {
        toast('Saved');
        s.reload();
      }}>
      <${Field} label="Remind admins to rotate after" id="rotation-reminder" help="rotation-reminder"
        error=${rec.error('keyReminderMonths')}>
        <${Select} value=${String(months)} onChange=${(/** @type {string} */ x) =>
          rec.set('keyReminderMonths', Number(x))} options=${options.sort((a, b) => a - b).map((
            m,
          ) => [String(m), m ? `${m} months` : 'Never'])} />
        </${Field}>
        </${DraftForm}>
  `;
}

/** The outcome of a re-encryption's copy, marked when the copy still opens with an old key
 * (S15.7.1.4). @param {string} o */
const leftUnder = (o) => o.startsWith('left');

function Keys() {
  const res = useApi('/settings/keys', {}, ['task']);
  const cps = useApi('/settings/keys/copies', {}, ['task']);
  const v = /** @type {any} */ (res.data);
  const copies = /** @type {any} */ (cps.data)?.copies || [];
  const [test, setTest] = useState(/** @type {any} */ (null));
  const [armed, setArmed] = useState(false);
  const verify = async () => {
    const r = await openDialog(VerifyKey);
    if (r) {
      toast(`These words open this server's key ${r.fingerprint}: recorded as checked`);
      res.reload();
    }
  };
  // The yearly alert opens Verify key itself (S12.11): /ui/settings/keys?verify.
  useEffect(() => {
    if (!new URLSearchParams(location.search).has('verify')) return;
    history.replaceState(null, '', location.pathname);
    verify().catch((e) => toast(e.message));
  }, []);
  const [choices, setChoices] = useState(/** @type {Record<string, string>} */ ({}));
  const reencrypt = useSubmit(async () => {
    await restartNow(() =>
      withReauth(() => api.post('/settings/keys/reencrypt', { copies: chosen(copies, choices) }))
    );
  });
  const rotate = () => openDialog(RotateKey, { copies }).catch((e) => toast(e.message));
  const removeCopy = async (/** @type {any} */ c) => {
    if (await openDialog(RemoveCopy, { c })) {
      toast(`${c.name} removed`);
      cps.reload();
      res.reload();
    }
  };
  const forget = async (/** @type {string} */ fp) => {
    const sure = await confirmAction({
      title: `Forget ${fp}?`,
      detail: 'A copy that needs it can no longer be opened here.',
      yes: 'Yes, forget it',
    });
    if (!sure) return;
    await withReauth(() => api.del(`/settings/keys/previous/${encodeURIComponent(fp)}`));
    toast(`${fp} forgotten`);
    res.reload();
  };
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} />`;
  const confirmed = v.confirmations.find((/** @type {any} */ c) => c.matched);
  const needing = (/** @type {string} */ fp) =>
    copies.filter((/** @type {any} */ c) => c.masterKey === fp).length;
  const last = v.lastReencryption;
  const lastCopies = last ? Object.entries(last.copies) : [];
  return html`
    <div class="card"><h3>Key storage<span class="spacer"></span>${test
      ? test.ok
        ? html`<span class="pill ok"><${Icon} name="lock" /> everything opens</span>`
        : html`<span class="pill bad">a problem</span>`
      : null}</h3>
        <p class="small dim" style=${{
          marginTop: 0,
        }}>The master key is the recovery phrase, never stored: it is entered when the server starts.
          Rotate changes it, and re-encrypts everything under a new data key.</p>
        <div class="list-item"><span class="grow dim">Fingerprint</span><code>${v
          .fingerprint}</code></div>
        <div class="list-item"><span class="grow dim">Made</span>${day(v.created)} · ${v
          .ageDays} days old
          ${v.reminderMonths
            ? html`<span class="small dim"> · rotation reminder at ${v.reminderMonths} months</span>`
            : null}
          ${v.reminderDue
            ? html`
              <span class="pill warn">time to rotate</span>
            `
            : null}</div>
        <div class="list-item"><span class="grow dim">Encrypted under it</span>the database (${(v
          .databaseBytes / 1048576).toFixed(1)} MB), ${v.receipts} receipt file${v.receipts === 1
          ? ''
          : 's'}, ${v.secrets} secret${v.secrets === 1 ? '' : 's'}
          <span class="small dim">· passwords are hashed</span></div>
        <div class="list-item"><span class="grow dim">Previous keys</span>${v.previous.length
          ? html`<span>${
            v.previous.map((/** @type {any} */ p) =>
              html`<div><code>${p.fingerprint}</code> <span class="small dim">· needed by ${
                needing(p.fingerprint)
              } ${needing(p.fingerprint) === 1 ? 'copy' : 'copies'} here${
                p.removableAfter ? `, and by the host's snapshots until it prunes them` : ''
              }</span>
            <button type="button" class="btn sm" onClick=${() =>
                forget(p.fingerprint).catch((e) => toast(e.message))}>Forget</button></div>`
            )
          }</span>`
          : html`<span class="dim">none</span>`}</div>
        <div class="list-item"><div class="grow"><span class="dim">Copies on this host</span>
          ${copies.length
            ? html`
              <table class="t mt">
                <caption class="sr-only">Copies on this host</caption>
                <thead>
                  <tr>
                    <th>Copy</th>
                    <th>Made</th>
                    <th class="num">Size</th>
                    <th>Opens</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>${copies.map((/** @type {any} */ c) =>
                  html`
                    <tr>
                      <td><code>${c.name}</code><div class="small dim">${c.what}</div></td>
                      <td>${moment(c.made)}</td>
                      <td class="num">${(c.bytes / 1048576).toFixed(1)} MB</td>
                      <td class="small">${opensWith(c.opens)}${c.masterKey
                        ? html`${' '}<code>${c.masterKey}</code>`
                        : null}</td>
                      <td><button type="button" class="btn sm" onClick=${() =>
                        removeCopy(c).catch((e) => toast(e.message))}>Remove</button></td>
                    </tr>
                  `
                )}</tbody>
              </table>
            `
            : html`<span class="small dim"> none</span>`}
          <div class="small dim">${/** @type {any} */ (cps.data)?.note || ''}</div></div></div>
        <div class="list-item"><div class="grow">Recovery phrase<div class="small dim">${confirmed
          ? `Last confirmed ${
            confirmed.how === 'unlock'
              ? 'by the unlock'
              : confirmed.how === 'app'
              ? 'with Verify key'
              : 'with moolakata keys verify'
          } on ${day(confirmed.at)}.`
          : 'Not confirmed since install. Every unlock confirms it; check each copy once a year with Verify key.'}</div></div>
          ${confirmed
            ? html`<span class="pill ok"><${Icon} name="check" /> confirmed</span>`
            : html`<span class="pill warn">unchecked</span>`}<button type="button" class="btn sm" onClick=${() =>
            verify().catch((e) => toast(e.message))}>Verify key</button></div>
        ${last
          ? html`
            <div class="list-item" data-help="last-reencryption">
              <div class="grow"><span class="dim">Last re-encryption</span>
                      <div class="small">${day(last.finishedAt)}${last.why === 'rotation'
                        ? ', with a rotation'
                        : last.why === 'host'
                        ? ', on the host'
                        : ', from Settings'}${last.receiptsSetAside.length ||
                          last.secretsSetAside.length
                        ? html`
                          : set aside ${last.receiptsSetAside.length} receipt files and left ${last
                            .secretsSetAside
                            .length} secrets that opened under neither key (the files are in <code
                          >receipts-set-aside/</code> in the data directory)
                        `
                        : ': everything opened'}.</div>
                      ${last.rotationUnfinished
                        ? html`
                          <div class="notice small bad mt" role="status">
                            <${Icon} name="alert" />
                            <div>The
                                        rotation didn't finish: the keyring stayed under <code>${last
                                          .rotationUnfinished}</code>, so it re-encrypted under that phrase. Rotate again.</div>
                          </div>
                        `
                        : null}
                      ${lastCopies.length
                        ? html`<ul class="small" style=${{ margin: '4px 0 0' }}>${
                          lastCopies.map(([name, o]) =>
                            html`<li><code>${name}</code>: ${o}${
                              leftUnder(String(o))
                                ? html`
                                  <span class="pill warn">still opens with an old key</span>
                                `
                                : null
                            }</li>`
                          )
                        }</ul>`
                        : null}</div>
            </div>
          `
          : null}
        <div class="notice mt"><${Icon} name="alert" /><div>Without the recovery phrase, nothing here and no backup can be
          opened, and the server cannot even start serving. Keep the phrase in two places, one offline.</div></div>
        ${test
          ? html`<ul class="small">${
            test.checks.map((/** @type {any} */ c) =>
              html`<li>${c.ok ? '✓' : '✗'} <b>${c.name}</b>: ${c.detail}</li>`
            )
          }</ul>`
          : null}
        ${v.scheduled
          ? html`
            <div class="notice mt" role="status" data-help="scheduled">
              <${Icon} name="refresh" />
              <div
                class="grow">A re-encryption${v.scheduled.why === 'rotation'
                  ? ', brought by a rotation,'
                  : ''} waits for the restart: the unlock runs it before the server serves, with the phrase
                      given there, its progress on the locked screen.</div>
            </div>
          `
          : null}${v.lastRestore &&
            (v.lastRestore.receiptsUnopened.length || v.lastRestore.secretsUnopened.length ||
              v.lastRestore.receiptsSetAside.length)
          ? html`
            <div class="notice small bad mt" role="status" data-help="after-restore">
              <${Icon}
                name="alert" />
              <div>After the restore of <code>${v.lastRestore.source}</code>:
                      ${v.lastRestore.receiptsUnopened
                        .length} receipts' files don't open (or are missing),
                      ${v.lastRestore.secretsUnopened.length} secrets don't open, and
                      ${v.lastRestore.receiptsSetAside
                        .length} files were set aside. Put the receipts back from
                      the host's own backup of the same moment; enter the secrets again.</div>
            </div>
          `
          : null}
        <div class="toolbar mt"><button type="button" class="btn" onClick=${() =>
          api.post('/settings/keys/test').then(setTest)}>Test</button>
          ${armed || v.scheduled ? null : html`
            <button type="button" class="btn" onClick=${rotate}>Rotate</button>
            <button type="button" class="btn" onClick=${() =>
              setArmed(true)}>Re-encrypt now</button>
          `}
          <span class="small dim">Rotate gives a new phrase, for a leaked or lost one or the yearly
            reminder. Re-encrypt now keeps the phrase and makes a new data key, for when the data key
            may have been read: a memory dump or a debugging session. Both restart MoolaKata, which
            then asks for the phrase.</span></div>
        ${armed
          ? html`
            <form class="mt" onSubmit=${(/** @type {Event} */ e) => {
              e.preventDefault();
              reencrypt.run().catch(() => {});
            }}>
              <p class="small dim" style=${{
                marginTop: 0,
              }}>MoolaKata restarts at once, locked. At the
                unlock, before it serves: a verified backup first; then the database, the receipt
                files and every secret are rewritten under a new data key, and the copies below as
                you choose. The phrase given at the unlock wraps the new key.</p>
              <${CopyChoices} copies=${copies} choices=${choices} set=${setChoices} />
              <${FormError} error=${reencrypt.error} />
              <div
                class="toolbar"><button class="btn primary" disabled=${reencrypt
                  .busy}>Re-encrypt and restart</button>
                        <button type="button" class="btn" onClick=${() =>
                          setArmed(false)}>Cancel</button></div>
            </form>
          `
          : null}
      </div>
    <${ReminderSetting} />
  `;
}
