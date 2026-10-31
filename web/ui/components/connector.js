// Settings › Connector (requirements S16.18, S18.4, S18.5): pairing with the MoolaKata
// Connector, whether it is locked, its last report, and every Connection's state, owner and
// accounts, never their credentials.
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useSubmit } from '../app/hooks.js';
import { ago, moment } from '../app/format.js';
import { withReauth } from './reauth.js';
import { Dialog, openDialog } from './dialog.js';
import { useDialogGuide } from './help.js';
import { Field, FormError, Input } from './fields.js';
import { Failed, Loading } from './bits.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';
import { confirmAction } from './confirm.js';
import { DraftForm } from './draft-form.js';
import { useSettingsDraft } from './settings-draft.js';

export const DRIVERS = /** @type {Record<string, string>} */ ({
  folder: 'Folder',
  'ofx-direct': 'OFX Direct Connect',
  schwab: 'Schwab',
});
const STATE = /** @type {Record<string, [string, string]>} */ ({
  new: ['waiting for credentials', ''],
  ok: ['ok', 'ok'],
  'needs-sign-in': ['needs a sign-in', 'warn'],
  failing: ['failing', 'bad'],
  removed: ['removed', ''],
});

/** @param {any} c */
export function connectionState(c) {
  const [label, tone] = STATE[c.state] || [c.state, ''];
  const detail = c.state === 'ok' && c.lastRunAt
    ? ` · ${c.lastRunAdded != null ? `${c.lastRunAdded} new · ` : ''}${ago(c.lastRunAt)}`
    : c.message && c.state !== 'ok'
    ? ` · ${c.message}`
    : '';
  return html`<span class=${'pill ' + tone}>${label}${detail}</span>`;
}

export function ConnectorSection() {
  const res = useApi('/settings/connector', {}, ['task']);
  const s = useApi('/settings');
  const v = /** @type {any} */ (res.data);
  const values = /** @type {any} */ (s.data)?.values;
  // The address a pairing code carries (S18.4.1): the connector's own, else the public URL.
  const fd = useSettingsDraft(s.data, ['connectorAddress']);
  const rec = fd.rec;
  const unpair = useSubmit(async () => {
    await withReauth(() => api.post('/settings/connector/unpair'));
    toast('Unpaired: every Connection stopped and every sync is off');
    res.reload();
  });
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v || !values || !rec) return html`<${Loading} />`;
  const paired = v.state === 'paired';
  const tone = !paired ? '' : v.silentForSeconds ? 'bad' : v.locked ? 'warn' : 'ok';
  const status = !paired
    ? v.state === 'pairing' ? 'pairing code out' : 'not paired'
    : v.silentForSeconds
    ? `not heard from for ${Math.round(v.silentForSeconds / 60)} min`
    : v.locked
    ? 'paired · locked'
    : 'paired · unlocked';
  return html`
    <div class="card">
      <h3>MoolaKata Connector<span class="spacer"></span><span class=${'pill ' + tone}><${Icon}
          name=${paired && !v.locked ? 'check' : 'lock'} /> ${status}</span></h3>
      <p class="small dim" style=${{ marginTop: '-6px' }}>A second service that holds
        institutions' credentials, fetches with its drivers and pushes into imports.
        MoolaKata can't reach it or read its vault: it only hears its signed reports.</p>
      ${paired
        ? html`
          <div class="list-item"><span class="grow dim">Connector</span><code
              class="mono small">${v.fingerprint}</code>${v.connectorVersion
                ? html`
                  <span class="small dim">· version ${v.connectorVersion}</span>
                `
                : null}</div>
          ${v.page
            ? html`
              <div class="list-item" data-help="its-page"><span class="grow dim">Its page</span><a
                  class="mono small" href=${v.page} target="_blank" rel="noopener noreferrer"
                >${v.page}</a><span class="small dim">· unlock, pair and lock it there</span></div>
            `
            : null}
          ${v.confirmedAt
            ? html`
              <div
                class="list-item"><span class="grow dim">Confirmed</span>${moment(
                  v.confirmedAt,
                )}${v.confirmedBy
                  ? ` by ${v.confirmedBy}`
                  : ''} <span class="small dim">· the fingerprints were compared</span></div>
            `
            : html`<div class="notice"><${Icon} name="alert" /><div>Compare the fingerprint above with
                the one the connector's page showed, or that${' '}
                <code>moolakata-connector pair</code>${' '}
                printed on its host. If they match, confirm: until then the connector gets no
                sign-in and posts no file. If they differ, someone else answered the code first:
                unpair.</div>
                <button class="btn primary" onClick=${() =>
              withReauth(() => api.post('/settings/connector/confirm')).then(() => {
                toast('Pairing confirmed');
                res.reload();
              }, (e) => toast(e.message))}>Confirm</button></div>`}
          ${v.newAddress
            ? html`<div class="notice" data-help="accept"><${Icon} name="alert" /><div>The connector
                reports from <code>${v.newAddress}</code>, not its known address <code>${v.knownAddress}</code>.
                If it moved, accept the new address; if not, its host or volume may have been copied:
                unpair it now.</div>
                <button class="btn" onClick=${() =>
              withReauth(() => api.post('/settings/connector/accept-address')).then(() => {
                toast('Address accepted');
                res.reload();
              }, (e) => toast(e.message))}>Accept</button></div>`
            : null}
          <div class="list-item"><span class="grow dim">Last report</span>${v.lastReportAt
            ? html`${ago(v.lastReportAt)}${
              v.pairedAt
                ? html`
                  <span class="small dim">· paired ${moment(v.pairedAt)}${v.pairedBy
                    ? ` by ${v.pairedBy}`
                    : ''}</span>
                `
                : null
            }`
            : 'never'}</div>
        `
        : v.state === 'pairing'
        ? html`
          <div class="notice">
            <${Icon} name="info" />
            <div>A pairing code is out until
                      ${moment(v.codeExpiresAt)}. Paste it into Pair on the connector's page (or run
                      it on its host), then compare the fingerprint both sides show.</div>
          </div>
        `
        : html`
          <div class="notice">
            <${Icon} name="info" />
            <div>No connector is paired. This
                      server's key fingerprint, which the pairing code carries:${' '}
                      <code>${v.serverFingerprint}</code></div>
          </div>
        `}
      <${DraftForm} f=${fd} class="draft-form mt" where="Settings › Connector"
        what="The address the connector reaches MoolaKata at" saved=${() => {
          toast('Saved');
          s.reload();
        }}>
        <${Field} label="The connector reaches MoolaKata at" id="connector-address"
          error=${rec.error('connectorAddress')}
          hint=${`The address a pairing code carries: on the connector's network, often this server's own. Empty: the public URL${
            values.publicUrl ? ` (${values.publicUrl})` : ', which is not set'
          }.`}>
          <${Input} value=${rec.get('connectorAddress') || ''} onInput=${(
            /** @type {string} */ x,
          ) => rec.set('connectorAddress', x || null)} placeholder="https://money.lan:37373" />
        </${Field}>
      </${DraftForm}>
      <div class="toolbar mt">
        <button class="btn" onClick=${() =>
          openDialog(PairDialog, {}).then(() => res.reload())}>${paired
          ? 'Pair a replacement…'
          : 'Pair…'}</button>
        <span class="spacer"></span>
        ${paired || v.state === 'pairing'
          ? html`<button class="btn danger" disabled=${unpair.busy} onClick=${async () => {
            const sure = await confirmAction({
              title: 'Unpair the connector?',
              detail: "Every Connection stops and every account's sync turns off.",
              yes: 'Yes, unpair',
            });
            if (sure) unpair.run().catch(() => {});
          }}>Unpair…</button>`
          : null}
      </div>
      <${FormError} error=${unpair.error} />
    </div>
    <div class="card">
      <h3>Connections</h3>
      <p class="small dim" style=${{ marginTop: '-6px' }}>Each person's sign-ins, kept by the
        connector. Their credentials are never shown here.</p>
      ${v.connections.length
        ? html`
          <div class="table-wrap">
            <table class="t">
              <caption class="sr-only">Connections</caption>
              <thead>
                <tr>
                  <th>Connection</th>
                  <th>Owner</th>
                  <th>Accounts</th>
                  <th data-help="host">Host</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>${v.connections.map((/** @type {any} */ c) =>
                html`
                  <tr>
                    <td><b>${c.label}</b><div class="small dim">${DRIVERS[c.driver] ||
                      c.driver} driver</div></td>
                    <td>${c.ownerName}</td>
                    <td class="small">${c.accounts.length
                      ? c.accounts.map((/** @type {any} */ a) =>
                        `${a.name}${a.syncAccount ? ` (${a.syncAccount})` : ''}`
                      ).join(' · ')
                      : html`<span class="dim">none yet</span>`}</td>
                    <td class="mono small">${c.host ||
                      html`<span class="dim">not set</span>`}</td>
                    <td>${connectionState(c)}${c.credentialWaiting
                      ? html`<div class="small dim">credentials waiting for the connector</div>`
                      : null}</td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        `
        : html`<p class="small dim">None yet. Each person starts their own under Profile ›
            Connections once a connector is paired.</p>`}
    </div>
  `;
}

/** @param {{ close: (v?: any) => void }} p */
function PairDialog({ close }) {
  useDialogGuide('dialog-connector-pair');
  const [made, setMade] = useState(/** @type {any} */ (null));
  const make = useSubmit(async () => {
    setMade(await withReauth(() => api.post('/settings/connector/pairings')));
  });
  useEffect(() => {
    make.run().catch(() => {});
  }, []);
  return html`
    <${Dialog} title="Pair a connector" close=${close} onSubmit=${() => close(true)}
      note="The code works once, for 24 hours."
      footer=${html`
        <button type="button" class="btn" disabled=${!made} onClick=${() =>
          navigator.clipboard?.writeText(made.code).then(() => toast('Copied'))}>Copy the
          code</button>
        <button class="btn primary">Done</button>
      `}>
      <p class="small dim" style=${{ marginTop: 0 }}>Paste this code into <b>Pair</b> on the
        connector's page, with its words. It holds this server's address and key fingerprint;
        the connector then introduces itself, and both sides show its fingerprint for you to
        compare.</p>
      ${make.error ? html`<${FormError} error=${make.error} />` : made
        ? html`
          <div class="field"
            data-help="pairing-code"><code class="mono" style=${{
              display: 'block',
              padding: '10px 12px',
              background: 'var(--bg-3)',
              borderRadius: '8px',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}>${made.code}</code></div>
          <p class="small dim">Or, with Docker Compose on the connector's host: <code
              class="mono">${made.command}</code></p>
        `
        : html`<${Loading} lines=${2} />`}
      <div class="notice mt"><${Icon} name="info" /><div>Pairing another connector replaces
        the one paired: its Connections stop and their accounts' sync turns off, as Unpair
        does.</div></div>
    </${Dialog}>
  `;
}
