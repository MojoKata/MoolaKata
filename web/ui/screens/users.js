// Users and Groups, for admins (requirements S10.1): invitations, the active switch, groups and
// the built-in Admins group.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useList, useSubmit } from '../app/hooks.js';
import { ago, day } from '../app/format.js';
import { useTitle } from '../components/frame.js';
import { useDialogGuide, useGuide } from '../components/help.js';
import { Avatar, Chips, Failed, Loading } from '../components/bits.js';
import { Icon } from '../components/icon.js';
import { Dialog, openDialog } from '../components/dialog.js';
import { Field, FormError, Input, Switch } from '../components/fields.js';
import { toast } from '../components/toast.js';
import { withReauth } from '../components/reauth.js';
import { Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { DraftDialog, RecField, saveNow, useDraft } from '../components/draft-form.js';

export default function Users() {
  useTitle('Users and Groups');
  useGuide('users');
  const users = useList('/users');
  const groups = useList('/groups');
  const requests = useList('/signup-requests', {}, ['signup']);
  const [show, setShow] = useState('active');
  const [busy, setBusy] = useState('');
  const u = /** @type {any[]} */ (users.data);
  const g = /** @type {any[]} */ (groups.data);
  if (users.error) return html`<${Failed} error=${users.error} />`;
  if (!u || !g) return html`<${Loading} lines=${8} />`;
  const name = (/** @type {string} */ id) => g.find((x) => x.id === id)?.name;
  const reload = () => {
    users.reload();
    groups.reload();
    requests.reload();
  };
  const setActive = async (/** @type {any} */ x, /** @type {boolean} */ on) => {
    setBusy(x.id);
    try {
      await saveNow((d) => d.load(UserRec, x).set('active', on));
      toast(`${x.displayName} is ${on ? 'active again' : 'inactive: their sessions ended'}`);
    } catch (e) {
      toast(/** @type {any} */ (e).message);
    } finally {
      setBusy('');
      reload();
    }
  };
  const asked = u.filter((x) => !x.active && x.reactivationAskedAt);
  const list = u.filter((x) => show === 'all' || x.active);
  const waiting = /** @type {any[]} */ (requests.data || []);
  return html`
    ${waiting.length
      ? html`<div class="card"><h3>Requests<span class="pill warn">${waiting.length}</span></h3>
        ${waiting.map((r) => html`<${SignupRequest} r=${r} groups=${g} done=${reload} />`)}</div>`
      : null}
    ${asked.length
      ? html`<div class="card"><h3>Asked to be made active again<span class="pill warn">${asked.length}</span></h3>
      ${
        asked.map((x) =>
          html`<div class="list-item"><${Avatar} name=${x.displayName} image=${x.avatar} id=${x.id} />
        <div class="grow">${x.displayName} · ${x.email}<div class="small dim">asked ${
            ago(x.reactivationAskedAt)
          }</div></div>
        <button type="button" class="btn sm primary" onClick=${() =>
            setActive(x, true)}>Make active</button></div>`
        )
      }</div>`
      : null}
    <div class="toolbar mt"><h2 style=${{
      margin: 0,
      fontSize: '15px',
    }}>Users</h2><span class="spacer"></span>
      <${Chips} label="Show" value=${show} onChange=${setShow} options=${[['active', 'Active'], [
        'all',
        'All, with inactive',
      ]]} />
      <button type="button" class="btn primary" onClick=${() =>
        openDialog(NewUser, { groups: g }).then((x) => x && reload())}>
        <${Icon} name="plus" /> New user</button></div>
    <div class="card" style=${{ padding: '4px 8px' }}>
      <table class="t">
        <caption class="sr-only">Users</caption>
        <thead>
          <tr>
            <th>Name</th>
            <th>Username</th>
            <th>Email</th>
            <th></th>
            <th class="num">Active</th>
          </tr>
        </thead>
        <tbody>${list.map((x) =>
          html`
            <tr>
              <td>
                <div class="acct-row">
                  <${Avatar} name=${x.displayName} image=${x.avatar} id=${x.id} />
                  <div>
                    <div class="name">${x.displayName}</div>
                    <div class="small">${x.groupIds.length
                      ? x.groupIds.map((/** @type {string} */ id) =>
                        html`
                          <span class="pill">${name(id)}</span>
                        `
                      )
                      : html`<span class="dim">no groups</span>`}</div>
                  </div>
                </div>
              </td>
              <td class="dim">${x.username}</td>
              <td class="dim">${x.email}</td>
              <td>${x.invited
                ? html`
                  <span class="pill warn">invited</span> <button type="button" class="btn sm"
                    onClick=${() =>
                      api.post(`/users/${x.id}/invitation`).then(
                        () => toast('Invitation sent again'),
                        (e) => toast(e.message),
                      )}>Resend invitation</button>
                `
                : html`
                  ${x.twoStep
                    ? html`
                      <span class="pill ok">two-step</span>
                    `
                    : null}<span
                    class="small dim">${x.lastSignInAt
                      ? 'signed in ' + ago(x.lastSignInAt)
                      : 'never signed in'}</span>
                `}
                      <button type="button" class="btn sm" onClick=${() =>
                        openDialog(EditUser, { user: x, groups: g }).then((r) =>
                          r && reload()
                        )}>Edit</button></td>
              <td class="num">
                <${Switch} on=${x.active} label=${'Active: ' +
                  x.displayName} disabled=${busy === x.id}
                  id=${'active-' + x.username} help="active" onChange=${(
                    /** @type {boolean} */ v,
                  ) => setActive(x, v)} />
              </td>
            </tr>
          `
        )}</tbody>
      </table>
    </div>
    <div class="toolbar mt"><h2 style=${{
      margin: 0,
      fontSize: '15px',
    }}>Groups</h2><span class="spacer"></span>
      <button type="button" class="btn" onClick=${() =>
        openDialog(GroupDialog, { users: u }).then((x) => x && reload())}>
        <${Icon} name="plus" /> New group</button></div>
    <div class="card" style=${{ padding: '4px 8px' }}>
      <table class="t">
        <caption class="sr-only">Groups</caption>
        <thead>
          <tr>
            <th>Name</th>
            <th>Members</th>
            <th>Made</th>
            <th class="num">Active</th>
          </tr>
        </thead>
        <tbody>${g.map((x) =>
          html`
            <tr class="click" onClick=${() =>
              openDialog(GroupDialog, { users: u, group: x }).then((r) => r && reload())}>
              <td><b>${x.name}</b>${x.builtIn
                ? html`
                  <span class="pill">built in</span>
                `
                : null}</td>
              <td>${x.memberIds.map((/** @type {string} */ m) => {
                const who = u.find((y) => y.id === m);
                return who
                  ? html`
                    <span title=${who.displayName}><${Avatar} sm name=${who.displayName} image=${who
                      .avatar} id=${who.id} /></span>
                  `
                  : null;
              })}</td>
              <td class="dim">${day(x.createdAt)}</td>
              <td class="num">${x.active ? 'yes' : 'no'}</td>
            </tr>
          `
        )}</tbody>
      </table>
    </div>
  `;
}

/** A user, as an admin's draft edits them (S10.1). */
class UserRec extends Record {
  /** @override */
  static prefix = 'User';
  /** @override */
  static fields = FIELDS.UserRecord;
  /** @override */
  static defaults = { sex: null, active: true, groupIds: [] };
}

/** A group (S10.2). */
class GroupRec extends Record {
  /** @override */
  static prefix = 'Group';
  /** @override */
  static fields = FIELDS.GroupRecord;
  /** @override */
  static defaults = { active: true, memberIds: [] };
}

/** @param {{ close: (v?: any) => void, groups: any[] }} p */
function NewUser({ close, groups }) {
  useDialogGuide('dialog-new-user');
  const f = useDraft((draft) => {
    draft.add(UserRec, { displayName: '', username: '', email: '' });
  }, []);
  const rec = /** @type {UserRec | undefined} */ (f.draft?.records[0]);
  return html`
    <${DraftDialog} f=${f} title="New user" close=${close} what="This user"
      label="Send the invitation" note="They choose their own password from the invitation."
      saved=${(/** @type {any} */ o) => {
        const u = o.saved[0].record;
        toast(`Invitation sent to ${u.email}`);
        close(u);
      }}>
      ${rec
        ? html`
          <${RecField} rec=${rec} name="displayName" label="Name" id="display-name" />
          <${RecField} rec=${rec} name="sex" label="Sex" options=${[
            ['', 'Choose…'],
            ['female', 'Female'],
            ['male', 'Male'],
          ]} />
          <div class="row">
            <${RecField} rec=${rec} name="username" label="Username" />
            <${RecField} rec=${rec} name="email" label="Email address" id="email" type="email" />
          </div>
          <${GroupPicker} groups=${groups} ids=${rec.get('groupIds')} setIds=${(
            /** @type {string[]} */ v,
          ) => rec.set('groupIds', v)} error=${rec.error('groupIds')} />
        `
        : null}
    </${DraftDialog}>
  `;
}

/**
 * A sign-up request whose email is confirmed (S10.1.4): approve it, into a group if wanted,
 * or reject it. Either way the person gets an email.
 * @param {{ r: any, groups: any[], done: () => void }} p
 */
function SignupRequest({ r, groups, done }) {
  const [group, setGroup] = useState('');
  const decide = useSubmit(async (/** @type {boolean} */ yes) => {
    if (yes) {
      await withReauth(() =>
        api.post(`/signup-requests/${r.id}/approve`, { groupIds: group ? [group] : [] })
      );
      toast(`${r.displayName} can sign in now`);
    } else {
      await api.post(`/signup-requests/${r.id}/reject`);
      toast(`${r.displayName}'s request was turned down`);
    }
    done();
  });
  return html`
    <div class="list-item">
      <${Avatar} name=${r.displayName} id=${r.id} />
      <div
        class="grow">${r.displayName} · ${r.email}<div class="small dim">${r
          .username} · sign-up · ${ago(r.confirmedAt)}</div>${decide.error
          ? html`<div class="err">${decide.error.message}</div>`
          : null}</div>
      <select class="in" style=${{ maxWidth: '150px' }} aria-label=${'Group for ' + r.displayName}
        data-help="request-group" value=${group}
        onChange=${(/** @type {any} */ e) => setGroup(e.currentTarget.value)}>
        <option value="">No groups</option>
        ${groups.filter((x) => x.active).map((x) => html`<option value=${x.id}>${x.name}</option>`)}
      </select>
      <button type="button" class="btn sm" disabled=${decide.busy} onClick=${() =>
        decide.run(false).catch(() => {})}>Reject</button>
      <button type="button" class="btn sm primary" disabled=${decide.busy}
        onClick=${() => decide.run(true).catch(() => {})}>Approve</button>
    </div>
  `;
}

/** @param {{ close: (v?: any) => void, user: any, groups: any[] }} p */
function EditUser({ close, user, groups }) {
  useDialogGuide('dialog-edit-user');
  const f = useDraft((draft) => {
    draft.load(UserRec, user);
  }, [user.id]);
  const rec = /** @type {UserRec | undefined} */ (f.draft?.records[0]);
  const [password, setPassword] = useState('');
  const [needPassword, setNeed] = useState(false);
  const [resetting, setResetting] = useState(false);
  // The last resort when the app and the recovery codes are lost (S10.1.6): an action.
  const reset = useSubmit(async () => {
    if (needPassword) await api.post('/session/reauth', { password });
    try {
      close(await api.post(`/users/${user.id}/two-step/reset`));
    } catch (e) {
      if (/** @type {any} */ (e).code === 'reauth-required') {
        setNeed(true);
        return;
      }
      throw e;
    }
    toast(`Two-step sign-in is off for ${user.displayName}`);
  });
  if (resetting) {
    return html`
      <${Dialog} title="Reset two-step sign-in" close=${close}
        onSubmit=${() => reset.run().catch(() => {})}
        footer=${html`
          <button type="button" class="btn" onClick=${() =>
            setResetting(false)}>Back</button> <button class="btn danger"
            disabled=${reset.busy}>Turn it off</button>
        `}>
        <p>This turns off two-step sign-in for ${user.displayName}, so their password alone signs
          them in, and signs them out everywhere. Do it only when they have lost both their app and
          their recovery codes, and you know it is them asking.</p>
        <p class="small dim">They get an email saying so, and can turn it on again in Profile.</p>
        ${needPassword
          ? html`
            <${Field} label="Your password" id="reauth-password"
              hint="Asked again: it was over 10 minutes ago.">
              <${Input} type="password" value=${password} onInput=${setPassword}
                autocomplete="current-password" required />
              </${Field}>
          `
          : null}
        <${FormError} error=${reset.error} />
      </${Dialog}>
    `;
  }
  return html`
    <${DraftDialog} f=${f} title=${user.displayName} close=${close} what="This user"
      done="Saved" extra=${() =>
        user.twoStep
          ? html`
            <button type="button" class="btn" style=${{ marginRight: 'auto' }}
              onClick=${() => setResetting(true)}>Reset two-step</button>
          `
          : null}>
      ${rec
        ? html`
          <${RecField} rec=${rec} name="displayName" label="Name" id="display-name" />
          <${RecField} rec=${rec} name="email" label="Email address" id="email" type="email"
            disabled=${!user.invited} hint=${user.invited
              ? 'Fix it before they join; the invitation then goes to the new address.'
              : 'Once a user has joined, they change it themselves.'} />
          <${GroupPicker} groups=${groups} ids=${rec.get('groupIds')} setIds=${(
            /** @type {string[]} */ v,
          ) => rec.set('groupIds', v)} error=${rec.error('groupIds') || rec.error('memberIds')} />
        `
        : null}
    </${DraftDialog}>
  `;
}

/** @param {{ groups: any[], ids: string[], setIds: (v: string[]) => void, error?: string | null }} p */
function GroupPicker({ groups, ids, setIds, error }) {
  return html`<fieldset class="field" style=${{ border: 0, padding: 0, margin: '0 0 14px' }}>
    <legend class="small" style=${{ color: 'var(--fg-dim)' }}>Groups</legend>
    ${
    groups.filter((g) => g.active).map((g) =>
      html`<label class="list-item" style=${{ cursor: 'pointer' }}><input type="checkbox"
      checked=${ids.includes(g.id)} onChange=${() =>
        setIds(ids.includes(g.id) ? ids.filter((x) => x !== g.id) : [...ids, g.id])} />
      <span class="grow">${g.name}${
        g.builtIn
          ? html`
            <span class="small dim">· manages users, groups and Settings</span>
          `
          : null
      }</span></label>`
    )
  }
    ${error ? html`<div class="err">${error}</div>` : null}</fieldset>`;
}

/** @param {{ close: (v?: any) => void, users: any[], group?: any }} p */
function GroupDialog({ close, users, group }) {
  useDialogGuide('dialog-group');
  const f = useDraft((draft) => {
    if (group) draft.load(GroupRec, group);
    else draft.add(GroupRec, { name: '' });
  }, [group?.id]);
  const rec = /** @type {GroupRec | undefined} */ (f.draft?.records[0]);
  const ids = /** @type {string[]} */ (rec?.get('memberIds') || []);
  return html`
    <${DraftDialog} f=${f} title=${group ? group.name : 'New group'} close=${close}
      what="This group" done="Saved">
      ${rec
        ? html`
          <${RecField} rec=${rec} name="name" label="Name" disabled=${group?.builtIn} />
          ${group && !group.builtIn
            ? html`
              <${RecField} rec=${rec} name="active" label="Active"
                hint="An inactive group's shares give its members nothing." />
            `
            : null}
          <fieldset class="field" style=${{
            border: 0,
            padding: 0,
            margin: '14px 0',
          }}><legend class="small" style=${{ color: 'var(--fg-dim)' }}>Members</legend>
            ${users.filter((u) => u.active).map((u) =>
              html`<label class="list-item" style=${{ cursor: 'pointer' }}><input
                type="checkbox" checked=${ids.includes(u.id)} onChange=${() =>
                rec.set(
                  'memberIds',
                  ids.includes(u.id) ? ids.filter((x) => x !== u.id) : [...ids, u.id],
                )} />
                <${Avatar} sm name=${u.displayName} image=${u.avatar} id=${u.id} /><span
                  class="grow">${u.displayName}</span></label>`
            )}
            ${rec.error('memberIds')
              ? html`<div class="err">${rec.error('memberIds')}</div>`
              : null}</fieldset>
        `
        : null}
    </${DraftDialog}>
  `;
}
