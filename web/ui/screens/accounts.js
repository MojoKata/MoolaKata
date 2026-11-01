// Accounts (requirements S12.2.2): every account the user owns or holds a share of, grouped,
// each with its type, institution, balance, change, when it was last updated and its sharing
// marks (S10.6). New account and Import start here.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { useList } from '../app/hooks.js';
import { ago } from '../app/format.js';
import { useTitle } from '../components/frame.js';
import { useGuide } from '../components/help.js';
import { Amt } from '../components/amount.js';
import { Avatar, Chips, Empty, Failed, GROUP_LABELS, Loading, Tile } from '../components/bits.js';
import { Icon } from '../components/icon.js';
import { openDialog } from '../components/dialog.js';
import { ShareDialog } from '../components/share.js';
import { NewAccount } from './new-account.js';
import { ImportDialog } from './import.js';
import { BY_TYPE } from '../account-types/index.js';

const FILTERS = /** @type {[string, string][]} */ ([
  ['all', 'All'],
  ['mine', 'Mine'],
  ['with-me', 'Shared with me'],
  ['by-me', 'Shared by me'],
]);
const ORDER = [
  'banking',
  'investing',
  'retirement',
  'education',
  'crypto',
  'giving',
  'liabilities',
  'physical-assets',
];

/** The sharing marks on an account's row (S10.6). @param {{ a: any }} p */
export function ShareMarks({ a }) {
  if (a.access.mine) {
    return a.sharedWith
      ? html`<span class="mark" data-tip="Shared by me"><${Icon} name="share" /> ${a.sharedWith}</span>`
      : null;
  }
  return html`<span class="mark" data-tip=${`Shared with me by ${a.ownerName} (${
    a.access.writable ? 'write' : 'read'
  })`}>
    <${Avatar} sm name=${a.ownerName} image=${a.ownerAvatar} id=${a.ownerId} />
    <${Icon} name=${a.access.writable ? 'pencil' : 'eye'} label=${
    a.access.writable ? 'write' : 'read'
  } /></span>`;
}

export default function Accounts() {
  useTitle('Accounts');
  useGuide('accounts');
  const [filter, setFilter] = useState('all');
  const res = useList('/accounts', {}, ['import', 'share', 'prices']);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  const all = /** @type {any[] | null} */ (res.data);
  if (!all) return html`<${Loading} lines=${6} />`;
  const list = all.filter((a) =>
    filter === 'mine'
      ? a.access.mine
      : filter === 'with-me'
      ? !a.access.mine
      : filter === 'by-me'
      ? a.access.mine && a.sharedWith
      : true
  );
  const labels = /** @type {Record<string, string>} */ (GROUP_LABELS);
  const sum = (/** @type {any[]} */ xs) => {
    let cents = 0n;
    for (const a of xs) cents += BigInt(String(a.balance).replace('.', ''));
    const neg = cents < 0n;
    const s = (neg ? -cents : cents).toString().padStart(3, '0');
    return (neg ? '-' : '') + s.slice(0, -2) + '.' + s.slice(-2);
  };
  return html`
    <div
      class="toolbar"><${Chips} label="Show" value=${filter} onChange=${setFilter} options=${FILTERS} />
      <span class="spacer"></span>
      <button type="button" class="btn" disabled=${!all.some((a) => a.access.writable)}
        onClick=${() =>
          openDialog(ImportDialog, { accounts: all })}><${Icon} name="upload" /> Import</button>
      <button type="button" class="btn primary" onClick=${() => openDialog(NewAccount)}><${Icon}
        name="plus" /> New account</button></div>
    ${!list.length
      ? html`<${Empty}>${
        all.length
          ? 'No accounts match this filter.'
          : 'No accounts yet. Make one with New account, then import its files.'
      }</${Empty}>`
      : null}
    ${ORDER.map((g) => {
      const as = list.filter((a) => a.group === g);
      if (!as.length) return null;
      return html`
        <section aria-labelledby=${'g-' + g}>
          <div
            class="group-head"><h2 id=${'g-' + g}>${labels[g]}</h2><span class="dim small">${as
              .length}</span>
                  <span class="num"><${Amt} v=${sum(as)} /></span></div>
          <div class="card" style=${{ padding: '4px 8px' }}>
            <div class="table-wrap">
              <table class="t">
                <caption class="sr-only">${labels[g]} accounts</caption>
                <tbody>
                  ${as.map((a) =>
                    html`
                      <tr class="click">
                        <td><a href=${`/ui/accounts/${a.id}`} class="acct-row" style=${{
                          color: 'inherit',
                        }}>
                                    <${Tile} group=${a.group} icon=${BY_TYPE[a.type]
                                      ?.icon} /><div><div class="name">${a.name}</div>
                                    <div class="sub">${[
                                      a.institution,
                                      a.typeLabel,
                                      a.mask ? '··' + a.mask : null,
                                    ].filter(Boolean)
                                      .join(' · ')}${a.active
                                      ? ''
                                      : ' · closed'}</div></div></a></td>
                        <td>
                          <${ShareMarks} a=${a} />
                        </td>
                        <td class="small dim"><${Icon} name="sync" /> ${ago(a.lastUpdated)}
                                    ${a.mismatch
                                      ? html`
                                        <a class="pill warn" href=${`/ui/accounts/${a.id}/reconcile`}>mismatch</a>
                                      `
                                      : null}
                                    ${!a.mismatch && a.needsAnchor
                                      ? html`
                                        <a class="pill" href=${`/ui/accounts/${a.id}/reconcile`}>balance needed</a>
                                      `
                                      : null}</td>
                        <td class="num"><b><${Amt} v=${a.balance} /></b>${a.change != null
                          ? html`<div class="small"><${Amt} v=${a.change} signed /> <span class="dim">30d</span></div>`
                          : null}</td>
                        <td class="num">${a.access.shareable
                          ? html`
                            <button type="button" class="icon-btn" aria-label=${'Share ' +
                              a.name} data-tip="Share"
                              onClick=${() =>
                                openDialog(ShareDialog, { kind: 'account', id: a.id, name: a.name })
                                  .then(() => res.reload())}><${Icon} name="share" /></button>
                          `
                          : null}</td>
                      </tr>
                    `
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      `;
    })}
    <${LinkedHouseholds} />
  `;
}

/** What other households share with you, each in a window of its own (S12.10.1). */
function LinkedHouseholds() {
  const res = useList('/linked', {}, ['share', 'links']);
  const rows = /** @type {any[]} */ (res.data) || [];
  if (!rows.length) return null;
  return html`<section class="card mt" data-help="linked-households"><h3>Linked households</h3>
    <p class="small dim" style=${{ marginTop: '-6px' }}>What other households share with you
      opens in a window of its own, never mixed with yours.</p>
    ${
    rows.map((h) =>
      html`
        <a class="list-item" href=${`/ui/linked/${h.linkId}/`} target=${`mk-linked-${h.linkId}`}
          style=${{ color: 'inherit' }}><span class="brand-av" style=${{
            background: h.avatar?.color || '#7a4b9c',
          }}>${h.avatar?.initials || '?'}</span><span class="grow"><b>${h.name}</b><div
                  class="small dim">${h.items} item${h.items === 1
                    ? ''
                    : 's'} shared with you · synced ${ago(h.syncedAt)}${h.locked
                    ? ' · locked'
                    : ''}</div></span><${Icon} name="link" /></a>
      `
    )
  }</section>`;
}
