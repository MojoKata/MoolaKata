// The Share dialog (requirements S10.4): every active user, then every active group, each with
// None · Read · Write, then each linked server's people with None · Read; who has access through a group is shown "via" it. Nothing changes until
// Save. For a portfolio, it names the accounts each person can't see (S5.1.2).
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useSubmit } from '../app/hooks.js';
import { Dialog } from './dialog.js';
import { useDialogGuide } from './help.js';
import { FormError, Seg, Switch } from './fields.js';
import { Avatar, Loading, Tile } from './bits.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';
import { withReauth } from './reauth.js';

const LEVELS =
  /** @type {[string, string][]} */ ([['none', 'None'], ['read', 'Read'], ['write', 'Write']]);
const REMOTE = /** @type {[string, string][]} */ ([['none', 'None'], ['read', 'Read']]);

/** @param {{ close: (v?: any) => void, kind: 'account' | 'portfolio' | 'budget', id: string, name: string }} p */
export function ShareDialog({ close, kind, id, name }) {
  useDialogGuide('dialog-share');
  const [view, setView] = useState(/** @type {any} */ (null));
  const [users, setUsers] = useState(/** @type {Record<string, string>} */ ({}));
  const [groups, setGroups] = useState(/** @type {Record<string, string>} */ ({}));
  const [receipts, setReceipts] = useState(/** @type {Record<string, boolean>} */ ({}));
  // The grants as read: the dialog holds changes while they differ (S12.15.6). A share set is
  // replaced whole by its own PUT (G25).
  const [read, setRead] = useState('');
  const now = JSON.stringify({ users, groups, receipts });
  useEffect(() => {
    api.get(`/shares/${kind}/${id}`).then((v) => {
      setView(v);
      setUsers(
        Object.fromEntries(
          [...v.users, ...v.links.flatMap((/** @type {any} */ l) => l.users)].map((
            /** @type {any} */ u,
          ) => [u.id, u.level]),
        ),
      );
      setReceipts(
        Object.fromEntries(v.links.map((/** @type {any} */ l) => [l.linkId, l.includeReceipts])),
      );
      setGroups(Object.fromEntries(v.groups.map((/** @type {any} */ g) => [g.id, g.level])));
    });
  }, [kind, id]);
  useEffect(() => {
    if (view && !read) setRead(now);
  }, [view, now]);
  const save = useSubmit(async (/** @type {boolean} */ too = false) => {
    // Sharing with a linked server asks for the password again (S13.7.2).
    const out = await withReauth(() =>
      api.put(`/shares/${kind}/${id}`, {
        users,
        groups,
        receipts,
        shareAccountsToo: too,
      }, view?.version ?? 0)
    );
    if (too && out.alsoShared) {
      setView(out.view);
      toast(`${out.alsoShared} account${out.alsoShared === 1 ? '' : 's'} shared at read`);
      return;
    }
    toast('Sharing saved');
    close(out);
  });
  const hidden = view?.hidden || {};
  const hiddenNames = Object.entries(hidden).map(([uid, accts]) => ({
    who: view.users.find((/** @type {any} */ u) => u.id === uid)?.displayName,
    accounts: /** @type {string[]} */ (accts).map((a) =>
      view.accounts.find((/** @type {any} */ x) => x.id === a)?.name
    ),
  }));
  return html`
    <${Dialog} title=${`Share “${name}”`} close=${close} changed=${() => !!read && now !== read}
      onSubmit=${() => save.run().catch(() => {})}
      note="When someone loses access, it ends on their next request."
      footer=${html`
        <button type="button" class="btn" data-cancel>Cancel</button>
        <button class="btn primary" disabled=${save.busy || !view}>Save</button>
      `}>
        ${!view ? html`<${Loading} />` : html`
          ${hiddenNames.length
            ? html`
              <div class="notice warn" style=${{ marginBottom: '12px' }}>
                <${Icon} name="alert" />
                <div>
                        ${hiddenNames.map((h) =>
                          html`<div><b>${h.who}</b> can't see ${
                            h.accounts.join(', ')
                          }: they see only what is shared
            with them, and the rest is left out of the portfolio's figures.</div>`
                        )}
                        <div class="toolbar mt" style=${{ marginBottom: 0 }}><button type="button"
                          class="btn sm primary" onClick=${() =>
                            save.run(true).catch(() => {})}>Share these accounts too</button>
                          <span class="small dim">at Read, only accounts you own</span></div></div>
              </div>
            `
            : null}
          <div class="share-list">
            <h4>People</h4><div class="why">They see it in their lists. <b>Write</b> lets them change what
              it holds; never delete it, re-share it or see its keys.</div>
            ${view.users.length
              ? view.users.map((/** @type {any} */ u) =>
                html`
                  <div class="list-item">
                    <${Avatar} name=${u.displayName} image=${u.avatar} id=${u.id} />
                    <div class="grow">${u.displayName}${u.via.length
                      ? html`<div class="small dim">via ${
                        u.via.map((/** @type {any} */ v) => `${v.groupName} (${v.level})`).join(
                          ', ',
                        )
                      }</div>`
                      : null}</div>
                    <${Seg} label=${'Access for ' +
                      u.displayName} value=${users[u.id]} options=${LEVELS}
                      onChange=${(/** @type {string} */ v) => setUsers({ ...users, [u.id]: v })} />
                  </div>
                `
              )
              : html`<p class="small dim">No one else uses this server yet.</p>`}
            <h4>Groups</h4><div class="why">The same, for every member while they are in the group.</div>
            ${view.groups.map((/** @type {any} */ g) =>
              html`
                <div class="list-item">
                  <${Tile} group="physical-assets" icon="users" />
                  <div class="grow">${g.name}<div class="small dim">${g
                    .members} member${g.members === 1 ? '' : 's'}</div></div>
                  <${Seg} label=${'Access for ' + g.name} value=${groups[g.id]} options=${LEVELS}
                    onChange=${(/** @type {string} */ v) => setGroups({ ...groups, [g.id]: v })} />
                </div>
              `
            )}
            ${view.links.map((/** @type {any} */ l) =>
              html`
                <h4>On ${l.serverName}${l.householdName
                  ? html`
                    <span class="small dim">${l.householdName}</span>
                  `
                  : null}</h4>
                <div class="why" data-help="linked-people">People on a linked server, as it
                  names them: always Read, seen only in its window there.</div>
                ${l.users.map((/** @type {any} */ u) =>
                  html`
                    <div class="list-item">
                      <${Avatar} name=${u.displayName} id=${u.id} />
                      <div class="grow">${u.displayName}</div>
                      <${Seg} label=${'Access for ' + u.displayName} value=${users[u.id]}
                        options=${REMOTE} onChange=${(/** @type {string} */ v) =>
                          setUsers({ ...users, [u.id]: v })} />
                    </div>
                  `
                )}
                ${l.users.some((/** @type {any} */ u) => users[u.id] === 'read')
                  ? html`<div class="list-item"><span class="grow">Include receipts<div
                      class="small dim">Their images and the text read from them cross to ${l.serverName} too.</div></span><${Switch} label=${
                    'Include receipts for ' +
                    l.serverName
                  } id=${l.linkId} help="include-receipts" on=${!!receipts[
                    l.linkId
                  ]} onChange=${(/** @type {boolean} */ v) =>
                    setReceipts({ ...receipts, [l.linkId]: v })} /></div>`
                  : null}
              `
            )}
          </div>
        `}
        <${FormError} error=${save.error} />
      </${Dialog}>
  `;
}
