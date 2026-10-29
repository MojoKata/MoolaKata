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
import { loadSession } from '../store/session.js';
import { LinksSection } from '../components/links.js';
import { ConnectorSection } from '../components/connector.js';
import { withReauth } from '../components/reauth.js';
import { StorageSection } from '../components/storage.js';
import { DraftDialog, DraftForm, saveNow, useDraft } from '../components/draft-form.js';
import { Record as Rec } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { useSectionDraft, useSettingsDraft } from '../components/settings-draft.js';

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
  const rec = fd.draft?.records[0];
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
  const time = fd.draft?.records[0];
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

/**
 * Tax tables (S16.11): per year, the figures that ship with MoolaKata, each correctable if the
 * IRS changes it before an update; the shipped value again removes the correction.
 */
function TaxTables() {
  const [year, setYear] = useState(/** @type {number | null} */ (null));
  const res = useApi('/settings/tax-tables', year ? { year } : {});
  const v = /** @type {any} */ (res.data);
  // The year's figures as one record of a draft, saved by the tables' route.
  const fd = useSectionDraft(
    `tax-tables-${v?.year}`,
    v
      ? {
        version: v.version,
        values: Object.fromEntries(v.rows.map((/** @type {any} */ r) => [r.key, r.value])),
      }
      : null,
    (values, version) => api.put('/settings/tax-tables', { year: v.year, values }, version),
  );
  const rec = fd.draft?.records[0];
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v || !rec) return html`<${Loading} />`;
  const read = (/** @type {any} */ r) => (/** @type {string} */ text) => {
    const x = parse(r, text);
    return [x].flat().some((n) => Number.isNaN(n))
      ? { error: r.kind === 'numbers' ? 'Numbers, separated by commas.' : 'A number.' }
      : { value: { [r.key]: x } };
  };
  const groups = [...new Set(v.rows.map((/** @type {any} */ r) => r.group))];
  return html`
    <${DraftForm} f=${fd} class="card content-narrow" where="Settings › Tax tables"
      what=${`The ${v.year} tables`} saved=${() => {
        toast('Saved');
        res.reload();
      }}>
      <h3>Tax tables<span class="spacer"></span><select class="in" style=${{ maxWidth: '100px' }}
        aria-label="Year" id="f-year" value=${v.year} disabled=${fd.draft?.changed}
        title=${fd.draft?.changed ? 'Save or put back the changes first' : undefined}
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
                                aria-label=${r.label} value=${rec.typed(r.key) ??
                                  show(rec.get(r.key))} onInput=${(/** @type {any} */ ev) =>
                                  rec.inputAs(r.key, ev.currentTarget.value, read(r))} />${rec
                                    .error(
                                      r.key,
                                    )
                                  ? html`<div class="err">${rec.error(r.key)}</div>`
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
  const fd = useSettingsDraft(s.data, EMAIL_KEYS);
  const rec = fd.draft?.records[0];
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
  const fd = useSettingsDraft(s.data, BITCOIN_KEYS);
  const rec = fd.draft?.records[0];
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

function Backups() {
  const res = useApi('/settings/backups', {}, ['task']);
  const s = useApi('/settings');
  const v = /** @type {any} */ (res.data);
  const fd = useSettingsDraft(s.data, ['backupTime', 'backupCopies']);
  const rec = fd.draft?.records[0];
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
          <${Field} label="Copies kept" error=${rec.error('backupCopies')}><${Input}
          value=${rec.get('backupCopies')} inputmode="numeric" onInput=${(
            /** @type {string} */ x,
          ) => rec.set('backupCopies', x === '' ? '' : Number(x))} /></${Field}></div>
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
  // A copy under an earlier phrase can only be left or deleted (S15.7.2).
  const choiceOf = (/** @type {any} */ c) =>
    choices[c.name] || (c.opens === 'current' || c.opens === 'phrase' ? 'reencrypt' : 'leave');
  const reencrypt = useSubmit(async () => {
    const sent = Object.fromEntries(copies.map((/** @type {any} */ c) => [c.name, choiceOf(c)]));
    await withReauth(() => api.post('/settings/keys/reencrypt', { copies: sent }));
    toast('Scheduled for the next restart');
    setArmed(false);
    res.reload();
    cps.reload();
  });
  const unschedule = useSubmit(async () => {
    await api.del('/settings/keys/reencrypt');
    toast('The re-encryption is cancelled');
    res.reload();
  });
  const removeCopy = async (/** @type {any} */ c) => {
    if (await openDialog(RemoveCopy, { c })) {
      toast(`${c.name} removed`);
      cps.reload();
      res.reload();
    }
  };
  const forget = async (/** @type {string} */ fp) => {
    await withReauth(() => api.del(`/settings/keys/previous/${encodeURIComponent(fp)}`));
    toast(`${fp} forgotten`);
    res.reload();
  };
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} />`;
  const confirmed = v.confirmations.find((/** @type {any} */ c) => c.matched);
  const needing = (/** @type {string} */ fp) =>
    copies.filter((/** @type {any} */ c) => c.masterKey === fp).length;
  return html`<div class="card"><h3>Key storage<span class="spacer"></span>${
    test
      ? test.ok
        ? html`<span class="pill ok"><${Icon} name="lock" /> everything opens</span>`
        : html`<span class="pill bad">a problem</span>`
      : null
  }</h3>
    <p class="small dim" style=${{
    marginTop: 0,
  }}>Read only here, but for Verify key. The master key is the recovery phrase, never stored: it
      is entered when the server starts, and changed only on the host.</p>
    <div class="list-item"><span class="grow dim">Fingerprint</span><code>${v.fingerprint}</code></div>
    <div class="list-item"><span class="grow dim">Made</span>${
    day(v.created)
  } · ${v.ageDays} days old
      ${
    v.reminderMonths
      ? html`<span class="small dim"> · rotation reminder at ${v.reminderMonths} months</span>`
      : null
  }
      ${
    v.reminderDue
      ? html`
        <span class="pill warn">time to rotate</span>
      `
      : null
  }</div>
    <div class="list-item"><span class="grow dim">Encrypted under it</span>the database (${
    (v.databaseBytes / 1048576).toFixed(1)
  } MB), ${v.receipts} receipt file${v.receipts === 1 ? '' : 's'}, ${v.secrets} secret${
    v.secrets === 1 ? '' : 's'
  }
      <span class="small dim">· passwords are hashed</span></div>
    <div class="list-item"><span class="grow dim">Previous keys</span>${
    v.previous.length
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
      : html`<span class="dim">none</span>`
  }</div>
    <div class="list-item"><div class="grow"><span class="dim">Copies on this host</span>
      ${
    copies.length
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
      : html`<span class="small dim"> none</span>`
  }
      <div class="small dim">${/** @type {any} */ (cps.data)?.note || ''}</div></div></div>
    <div class="list-item"><div class="grow">Recovery phrase<div class="small dim">${
    confirmed
      ? `Last confirmed ${
        confirmed.how === 'unlock'
          ? 'by the unlock'
          : confirmed.how === 'app'
          ? 'with Verify key'
          : 'with moolakata keys verify'
      } on ${day(confirmed.at)}.`
      : 'Not confirmed since install. Every unlock confirms it; check each copy once a year with Verify key.'
  }</div></div>
      ${
    confirmed
      ? html`<span class="pill ok"><${Icon} name="check" /> confirmed</span>`
      : html`<span class="pill warn">unchecked</span>`
  }<button type="button" class="btn sm" onClick=${() =>
    verify().catch((e) => toast(e.message))}>Verify key</button></div>
    <div class="notice mt"><${Icon} name="alert" /><div>Without the recovery phrase, nothing here and no backup can be
      opened, and the server cannot even start serving. Keep the phrase in two places, one offline.</div></div>
    ${
    test
      ? html`<ul class="small">${
        test.checks.map((/** @type {any} */ c) =>
          html`<li>${c.ok ? '✓' : '✗'} <b>${c.name}</b>: ${c.detail}</li>`
        )
      }</ul>`
      : null
  }
    ${
    v.scheduled
      ? html`<div class="notice mt" role="status" data-help="scheduled"><${Icon} name="refresh" /><div
          class="grow">A re-encryption is scheduled for the next restart${
        v.scheduled.why ===
            'rotation'
          ? ', brought by a rotation on the host'
          : ''
      }. The next unlock runs it before the server serves, with the phrase given there,
          its progress on the locked screen.${
        v.scheduled.started ? ' It has begun, and finishes at the next unlock.' : ''
      }</div>${
        v.scheduled.started ? null : html`
          <button type="button" class="btn sm"
            disabled=${unschedule.busy} onClick=${() =>
              unschedule.run().catch(() => {})}>Cancel it</button>
        `
      }</div>`
      : null
  }${
    v.lastReencryption &&
      (v.lastReencryption.receiptsSetAside.length || v.lastReencryption.secretsSetAside.length)
      ? html`
        <div class="notice small bad mt" role="status">
          <${Icon} name="alert" />
          <div>The last
                  re-encryption, ${day(v.lastReencryption.finishedAt)}, set aside ${v
                    .lastReencryption
                    .receiptsSetAside.length} receipt files and left ${v.lastReencryption
                    .secretsSetAside
                    .length} secrets that opened under neither key: the files are in <code
                  >receipts-set-aside/</code> in the data directory.</div>
        </div>
      `
      : null
  }${
    v.lastRestore &&
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
      : null
  }
    <div class="toolbar mt"><button type="button" class="btn" onClick=${() =>
    api.post('/settings/keys/test').then(setTest)}>Test</button>
      ${
    armed || v.scheduled
      ? null
      : html`<button type="button" class="btn" onClick=${() =>
        setArmed(true)}>Re-encrypt at the next restart</button>`
  }
      <span class="small dim">A new data key, made at the next unlock before the server serves. For when the data key may have been read: a memory dump or a debugging session. A leaked phrase calls for a rotation, which re-encrypts too. It closes nothing made before it.</span></div>
    ${
    armed
      ? html`
        <form class="mt" onSubmit=${(/** @type {Event} */ e) => {
          e.preventDefault();
          reencrypt.run().catch(() => {});
        }}>
          <p class="small dim" style=${{ marginTop: 0 }}>At the next unlock, before the server
            serves: a verified backup first; then the database, the receipt files and every
            secret are rewritten under a new data key, and the copies below as you choose. The
            phrase given at the unlock wraps the new key.</p>
            ${copies.length
              ? html`<div class="field" data-help="copies-at-re-encryption"><label>The copies on this host</label>
                ${
                copies.map((/** @type {any} */ c) =>
                  html`
                    <div class="list-item">
                      <div class="grow"><code>${c.name}</code>
                                        <div class="small dim">${c.what} · ${opensWith(
                                          c.opens,
                                        )}</div></div>
                      <span
                        style=${{ flex: 'none', width: '180px' }}><${Select} value=${choiceOf(
                          c,
                        )} onChange=${(/** @type {string} */ x) =>
                          setChoices({ ...choices, [c.name]: x })} options=${[
                          ['reencrypt', 'Re-encrypt'],
                          ['delete', 'Delete'],
                          ['leave', 'Leave as it is'],
                        ]} /></span>
                    </div>
                  `
                )
              }
                <div class="small dim">A copy that needs a previous phrase can only be left or deleted.</div></div>`
              : null}
            <${FormError} error=${reencrypt.error} />
            <div class="toolbar"><button class="btn primary" disabled=${reencrypt
              .busy}>Schedule it</button>
                    <button type="button" class="btn" onClick=${() =>
                      setArmed(false)}>Cancel</button></div>
            </form>
      `
      : null
  }
  </div>`;
}
