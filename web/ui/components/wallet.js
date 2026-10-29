// A self-custody wallet's keys and addresses (requirements S1.6.1, S1.6.3): extended public keys
// (xpub, ypub, zpub) or addresses, never a private key or seed phrase. Text that looks like one
// is cleared from the form at once, before anything is sent; the server checks again.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useSubmit } from '../app/hooks.js';
import { ago } from '../app/format.js';
import { Field, FormError } from './fields.js';
import { RecField } from './draft-form.js';
import { Failed, Loading } from './bits.js';
import { toast } from './toast.js';

const SCRIPT = /** @type {Record<string, string>} */ ({
  p2pkh: 'legacy (1…)',
  'p2sh-p2wpkh': 'nested segwit (3…)',
  p2sh: 'script (3…)',
  p2wpkh: 'native segwit (bc1q…)',
  p2wsh: 'segwit script (bc1q…)',
  p2tr: 'taproot (bc1p…)',
});

/**
 * What secret the text looks like, if any: the same shapes the server refuses.
 * @param {string} text
 */
export function looksSecret(text) {
  // Twelve words in a row, one perhaps mistyped, however separated or numbered (1. or 1)).
  let run = 0, misses = 0;
  for (const tok of text.toLowerCase().split(/[\s,;]+/)) {
    if (!tok || /^\d+[.):]?$/.test(tok)) continue;
    if (/^(?:\d+[.):]?)?[a-z]{3,8}\.?$/.test(tok)) run += 1;
    else if (run && !misses) [run, misses] = [run + 1, 1];
    else [run, misses] = [0, 0];
    if (run >= 12) return 'seed phrase';
  }
  // A key alone or inside a descriptor: wpkh(…), [origin]xprv…/0/*.
  for (const tok of text.split(/[^0-9A-Za-z]+/)) {
    if (/^[0-9a-fA-F]{64}$/.test(tok)) return 'private key (64 hex digits)';
    if (/^[xyztuv]prv/.test(tok)) return 'extended private key';
    if (/^[5KLc9][1-9A-HJ-NP-Za-km-z]{50,51}$/.test(tok)) return 'private key (WIF)';
  }
  return null;
}

/** @param {string} what */
const refusal = (what) =>
  `That looks like a ${what}. MoolaKata never accepts one, and nothing was saved: enter an extended public key (xpub, ypub or zpub), a public descriptor or addresses instead.`;

/**
 * The keys box and gap limit, fields of the account's draft in the New account form and the
 * wallet's Settings. A secret is cleared from the box at once, never put in the draft.
 * @param {{ rec: import('../app/draft.js').Record }} p
 */
export function WalletFields({ rec }) {
  const [refused, setRefused] = useState(/** @type {string | null} */ (null));
  const onText = (/** @type {any} */ ev) => {
    const v = ev.currentTarget.value;
    const what = looksSecret(v);
    if (what) {
      ev.currentTarget.value = '';
      rec.input('walletKeys', '');
      setRefused(refusal(what));
    } else {
      setRefused(null);
      rec.input('walletKeys', v);
    }
  };
  return html`
    <${Field} label="Extended public keys or addresses" id="wallet-keys" error=${refused ||
      rec.error('walletKeys')}
      hint="An xpub, ypub or zpub, a descriptor (wpkh, tr, wsh multisig…), or addresses, one a line. Public data only.">
      <textarea class="in mono" rows="3" value=${rec.shown('walletKeys')} onInput=${onText}
        placeholder="zpub6r…, wpkh([…]xpub…/<0;1>/*)#…, or bc1q… one a line" spellcheck="false"
        autocomplete="off"></textarea>
      </${Field}>
      <${RecField} rec=${rec} name="gapLimit" label="Gap limit"
        hint="Addresses derived past the last one used. 20 suits most wallets." />
  `;
}

/**
 * The wallet's keys and the addresses it watches, on its Settings tab: the keys box is a field
 * of the Settings form's draft, saved with its Save.
 * @param {{ a: any, rec: import('../app/draft.js').Record }} p
 */
export function WalletCard({ a, rec }) {
  const res = useApi(`/accounts/${a.id}/wallet`);
  const v = /** @type {any} */ (res.data);
  const owner = ['owner', 'write'].includes(a.level);
  const check = useSubmit(async () => {
    const r = await api.post(`/accounts/${a.id}/wallet/sync`);
    toast(
      r.recorded
        ? `${r.recorded} transaction${r.recorded === 1 ? '' : 's'} recorded`
        : 'Checked: nothing new',
    );
    res.reload();
  });
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) {
    return html`
      <div class="card">
        <${Loading} lines=${4} />
      </div>
    `;
  }
  return html`
    <div class="card">
      <h3>Keys and addresses</h3>
      ${owner ? html`<${WalletFields} rec=${rec} />` : null}
      <p class="small dim" data-help="watched">${v.watched} addresses watched, ${v.used} used${v
          .checkedAt
        ? `, last checked ${ago(v.checkedAt)}`
        : ': not checked yet. Balances come from the explorer or node in Settings › Bitcoin.'}</p>
      ${v.keys.map((/** @type {any} */ k) =>
        html`
          <div class="list-item">
            <div
              class="grow"><span class="mono small">${k.value.length > 40
                ? k.value.slice(0, 12) + '…' + k.value.slice(-8)
                : k.value}</span><div class="small dim">${k.kind === 'xpub'
                ? `Extended public key · ${SCRIPT[k.script] || k.script} · ${k.addresses} addresses`
                : `Address · ${SCRIPT[k.script] || k.script}`}</div></div>
          </div>
        `
      )}
      ${v.addresses.length
        ? html`
          <details class="mt">
            <summary class="small">Addresses</summary>
            <div class="table-wrap">
              <table class="t">
                <caption class="sr-only">Addresses watched</caption>
                <thead>
                  <tr>
                    <th>Address</th>
                    <th>Chain</th>
                    <th class="num">Transactions</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>${v.addresses.map((/** @type {any} */ r) =>
                  html`
                    <tr>
                      <td class="mono small">${r.address}</td>
                      <td class="small dim">${r.chain ===
                          0
                        ? `receive ${r.index}`
                        : r.chain === 1
                        ? `change ${r.index}`
                        : 'typed'}</td>
                      <td class="num">${r.txCount}</td>
                      <td>${r.used ? html`<span class="pill">used</span>` : null}</td>
                    </tr>
                  `
                )}</tbody>
              </table>
            </div>
          </details>
        `
        : null}
      <${FormError} error=${check.error} />
      ${owner
        ? html`
          <div
            class="toolbar mt"><button type="button" class="btn" disabled=${check.busy ||
              !v.keys.length} onClick=${() => check.run().catch(() => {})}>Check now</button></div>
        `
        : null}
    </div>
  `;
}
