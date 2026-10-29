// The Share dialog (requirements S10.4): every active user, then every active group, each with
// None · Read · Write, then each linked server's people with None · Read; who has access through a group is shown "via" it. Nothing changes until
// Save, which saves the item's grants as records of a draft (S12.15). For a portfolio, it names
// the accounts each person can't see (S5.1.2).
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useDialogGuide } from './help.js';
import { Seg, Switch } from './fields.js';
import { Record as Rec } from '../app/draft.js';
import { DraftDialog, useDraft } from './draft-form.js';
import { FIELDS } from '../api/fields.js';
import { Avatar, Loading, Tile } from './bits.js';
import { Icon } from './icon.js';

const LEVELS =
  /** @type {[string, string][]} */ ([['none', 'None'], ['read', 'Read'], ['write', 'Write']]);
const REMOTE = /** @type {[string, string][]} */ ([['none', 'None'], ['read', 'Read']]);

/** A grant (S10.4): an item shared with a user or a group, a record of the dialog's draft. */
class ShareRec extends Rec {
  /** @override */
  static prefix = 'Share';
  /** @override */
  static fields = FIELDS.ShareRecord;
  /** @override */
  static defaults = { userId: null, groupId: null, includeReceipts: false };
}

/** @param {{ close: (v?: any) => void, kind: 'account' | 'portfolio' | 'budget', id: string, name: string }} p */
export function ShareDialog({ close, kind, id, name }) {
  useDialogGuide('dialog-share');
  const [view, setView] = useState(/** @type {any} */ (null));
  // Each grant the item has is a record; giving one adds it, None removes it (S12.15).
  const f = useDraft(async (draft) => {
    const v = await api.get(`/shares/${kind}/${id}`);
    const people = [...v.users, ...v.links.flatMap((/** @type {any} */ l) => l.users)];
    for (const u of people) {
      if (u.shareId) {
        draft.load(ShareRec, {
          id: u.shareId,
          version: u.version,
          kind,
          itemId: id,
          userId: u.id,
          level: u.level,
          includeReceipts: u.includeReceipts,
        });
      }
    }
    for (const g of v.groups) {
      if (g.shareId) {
        draft.load(ShareRec, {
          id: g.shareId,
          version: g.version,
          kind,
          itemId: id,
          groupId: g.id,
          level: g.level,
        });
      }
    }
    setView(v);
  }, [kind, id]);
  const draft = f.draft;
  const all = /** @type {ShareRec[]} */ (draft?.records || []);
  /** The grant for a user or a group, or for an account of a portfolio's, if any. */
  const grant = (/** @type {string} */ key, /** @type {string} */ who, item = id) =>
    all.find((r) => r.get(key) === who && r.get('itemId') === item);
  const level = (/** @type {string} */ key, /** @type {string} */ who) => {
    const r = grant(key, who);
    return r && !r.removed ? r.get('level') : 'none';
  };
  const linkOf = (/** @type {string} */ uid) =>
    view?.links.find((/** @type {any} */ l) =>
      l.users.some((/** @type {any} */ u) => u.id === uid)
    );
  const receiptsOn = (/** @type {any} */ l) =>
    l.users.some((/** @type {any} */ u) => {
      const r = grant('userId', u.id);
      return r && !r.removed && r.get('includeReceipts');
    });
  const setLevel = (/** @type {string} */ key, /** @type {string} */ who) =>
  (
    /** @type {string} */ v,
  ) => {
    if (!draft) return;
    const r = grant(key, who);
    if (v === 'none') {
      if (r) draft.remove(r);
      return;
    }
    if (r) {
      if (r.removed) draft.unremove(r);
      r.set('level', v);
      return;
    }
    const l = key === 'userId' ? linkOf(who) : null;
    draft.add(ShareRec, {
      kind,
      itemId: id,
      [key]: who,
      level: v,
      includeReceipts: !!(l && receiptsOn(l)),
    });
  };
  const setReceipts = (/** @type {any} */ l) => (/** @type {boolean} */ on) => {
    for (const u of l.users) {
      const r = grant('userId', u.id);
      if (r && !r.removed) r.set('includeReceipts', on);
    }
  };
  // Share these accounts too (S5.1.2): each hidden account the owner holds, at Read, saved
  // with the rest.
  const yours = new Set(
    (view?.accounts || []).filter((/** @type {any} */ a) => a.yours).map((/** @type {any} */ a) =>
      a.id
    ),
  );
  const pending = Object.entries(view?.hidden || {}).flatMap(([uid, accts]) =>
    /** @type {string[]} */ (accts).filter((a) => yours.has(a) && !grant('userId', uid, a)).map((
      a,
    ) => [uid, a])
  );
  const accountsToo = () => {
    for (const [uid, a] of pending) {
      draft?.add(ShareRec, { kind: 'account', itemId: a, userId: uid, level: 'read' });
    }
  };
  const users = Object.fromEntries(
    [...(view?.users || []), ...(view?.links || []).flatMap((/** @type {any} */ l) => l.users)]
      .map((/** @type {any} */ u) => [u.id, level('userId', u.id)]),
  );
  const groups = Object.fromEntries(
    (view?.groups || []).map((/** @type {any} */ g) => [g.id, level('groupId', g.id)]),
  );
  const receipts = Object.fromEntries(
    (view?.links || []).map((/** @type {any} */ l) => [l.linkId, receiptsOn(l)]),
  );
  const setUsers = (/** @type {Record<string, string>} */ next) => {
    for (const [uid, v] of Object.entries(next)) if (v !== users[uid]) setLevel('userId', uid)(v);
  };
  const setGroups = (/** @type {Record<string, string>} */ next) => {
    for (const [gid, v] of Object.entries(next)) if (v !== groups[gid]) setLevel('groupId', gid)(v);
  };
  const setReceiptsFor = (/** @type {Record<string, boolean>} */ next) => {
    for (const l of view?.links || []) {
      if (next[l.linkId] !== receipts[l.linkId]) setReceipts(l)(next[l.linkId]);
    }
  };
  const hidden = view?.hidden || {};
  const hiddenNames = Object.entries(hidden).map(([uid, accts]) => ({
    who: view.users.find((/** @type {any} */ u) => u.id === uid)?.displayName,
    accounts: /** @type {string[]} */ (accts).map((a) =>
      view.accounts.find((/** @type {any} */ x) => x.id === a)?.name
    ),
  }));
  return html`
    <${DraftDialog} f=${f} title=${`Share “${name}”`} close=${close} what="These shares"
      done="Sharing saved" saved=${() => close(true)}
      note="When someone loses access, it ends on their next request."
      extra=${() => html`<button type="button" class="btn" data-cancel>Cancel</button>`}>
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
                        <div class="toolbar mt" style=${{ marginBottom: 0 }}>${pending.length
                          ? html`
                            <button type="button" class="btn sm primary" onClick=${accountsToo}
                            >Share these accounts too</button>
                            <span class="small dim">at Read, only accounts you own</span>
                          `
                          : html`<span class="small dim">Shared at Read when you save.</span>`}</div></div>
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
                    setReceiptsFor({ ...receipts, [l.linkId]: v })} /></div>`
                  : null}
              `
            )}
          </div>
        `}
    </${DraftDialog}>
  `;
}
