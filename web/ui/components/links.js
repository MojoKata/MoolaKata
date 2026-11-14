// Settings › Linked Servers (requirements S11.1, S11.7): invite a server or enter its code,
// approve a request after comparing fingerprints, pause, resume, pull now or end a link, and
// each linked server's users.
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useSubmit } from '../app/hooks.js';
import { ago, day, moment } from '../kit/format.js';
import { parseDuration } from '../kit/duration.js';
import { withReauth } from './reauth.js';
import { confirmAction } from '../kit/confirm.js';
import { Dialog, openDialog } from '../kit/dialog.js';
import { useDialogGuide } from './help.js';
import { errAt, Field, FormError, Input, Select, TypedInput } from '../kit/fields.js';
import { Failed, Loading } from '../kit/bits.js';
import { Icon } from '../kit/icon.js';
import { toast } from '../kit/toast.js';
import { DraftForm } from './draft-form.js';
import { saveSetting, useSettingsDraft } from './settings-draft.js';
import { Empty, StatePill } from '../kit/state.js';

const KIND = /** @type {Record<string, string>} */ ({
  account: 'An account',
  portfolio: 'A portfolio',
  budget: 'A budget',
  'gift-plan': "A person's gifts",
  person: 'A person',
  'giving-plan': 'A giving plan',
  'tax-book': 'A tax book',
  projection: 'A projection',
});
/** A certificate key's fingerprint in groups of four, for two admins to read out. */
const grouped = (/** @type {string} */ fp) => (fp.match(/.{1,4}/g) || []).join(' ');

// A link's state: its pill's word and tone, and what a word needing it means.
const STATE = /** @type {Record<string, [string, string, string?]>} */ ({
  invited: ['invitation', ''],
  requested: ['request', 'info', 'The other server asks to link with this one.'],
  pending: ['waiting', '', 'Waiting for the other server to approve the link.'],
  active: ['active', 'ok'],
  paused: ['paused', 'warn'],
  ended: ['ended', ''],
});

/** A link's state as a pill: broken, unreachable, paused or its state. @param {any} l */
function linkState(l) {
  const [word, tone, said] = STATE[l.state];
  const why = l.brokenAt
    ? null
    : l.failingSince
    ? `Unreachable since ${day(l.failingSince)}.`
    : l.state === 'paused' && l.pausedUntil
    ? `Paused until ${moment(l.pausedUntil)}.`
    : said;
  const shown = l.brokenAt ? 'broken' : l.failingSince ? 'unreachable' : word;
  const hue = l.brokenAt ? 'bad' : l.failingSince ? 'warn' : tone;
  return why
    ? html`<${StatePill} tone=${hue} why=${why}>${shown}</${StatePill}>`
    : html`<span class=${'pill ' + hue}>${shown}</span>`;
}

export function LinksSection() {
  const res = useApi('/settings/links', {}, ['task']);
  const s = useApi('/settings');
  const v = /** @type {any} */ (res.data);
  const values = /** @type {any} */ (s.data)?.values;
  const fd = useSettingsDraft(s.data, ['linkAddress']);
  const rec = fd.rec;
  const act = useSubmit(async (/** @type {string} */ id, /** @type {string} */ what) => {
    const out = await withReauth(() => api.post(`/settings/links/${id}/${what}`));
    toast(
      what === 'pull'
        ? out.lastError ? `Not reached: ${out.lastError}` : 'Exchanged now'
        : what === 'accept-certificate'
        ? 'Its new certificate is accepted'
        : what === 'resume'
        ? 'Link resumed'
        : what === 'reset-copy'
        ? 'Resetting the copy: everything is pulled again'
        : `Link ${out.state === 'ended' ? 'ended' : out.state}`,
    );
    res.reload();
  });
  const pause = (/** @type {any} */ l) =>
    openDialog(PauseDialog, { link: l }).then((x) => x && res.reload());
  const copyAct = useSubmit(async (/** @type {string} */ id, /** @type {string} */ what) => {
    const out = await api.post(`/settings/links/${id}/${what}`);
    toast(what === 'lock' ? 'Locked' : 'Copy reset: make its new access key');
    res.reload();
    return out;
  });
  const release = useSubmit(async (/** @type {string} */ v) => {
    await saveSetting(s.data, 'linkReleaseMinutes', Number(v));
    toast('Saved');
    s.reload();
  });
  if (res.error || s.error) return html`<${Failed} error=${res.error || s.error} />`;
  if (!v || !values || !rec) return html`<${Loading} />`;
  const live = v.links.filter((/** @type {any} */ l) => l.state !== 'ended');
  const ended = v.links.filter((/** @type {any} */ l) => l.state === 'ended');
  const people = live.filter((/** @type {any} */ l) => l.users.length);
  return html`
    <div class="card">
      <h3 style=${{ flexWrap: 'wrap' }}>Linked Servers<span class="spacer"></span><button
        class="btn" onClick=${() =>
          openDialog(JoinLink, {}).then((x) => x && res.reload())}>Enter a Link Code</button>
        <button class="btn primary" onClick=${() =>
          openDialog(InviteLink, {}).then(() => res.reload())}><${Icon} name="plus" /> Invite a
          Server</button></h3>
      <div class="notice" style=${{ marginBottom: '12px' }}>
        <${Icon} name="info" />
        <div>This server's key fingerprint: <code>${v.fingerprint}</code>${v.certificate
          ? html`. Its own certificate's key: <code>${grouped(v.certificate)}</code>`
          : ''}</div>
      </div>
      <${DraftForm} f=${fd} class="draft-form mb" where="Settings › Linked Servers"
        what="This server's link address" saved=${() => {
          toast('Saved');
          res.reload();
          s.reload();
        }}>
        <${Field} label="This server's link address" id="link-address"
          error=${rec.error('linkAddress')}>
          <${Input} value=${rec.get('linkAddress') || ''} onInput=${(/** @type {string} */ x) =>
            rec.set('linkAddress', x || null)} placeholder=${values.publicUrl
            ? `the public URL (${values.publicUrl})`
            : 'the public URL, which is not set'} />
        </${Field}>
      </${DraftForm}>
      ${live.length
        ? html`
          <div class="table-wrap">
            <table class="t">
              <caption class="sr-only">Linked servers</caption>
              <thead>
                <tr>
                  <th>Server</th>
                  <th>State</th>
                  <th>Last Exchange</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>${live.map((/** @type {any} */ l) =>
                html`
                  <tr>
                    <td>
                      <div class="acct-row">
                        <div class=${'tile ' +
                          (l.state === 'active' ? 't-linked' : 't-other')}>
                          <${Icon} name="server" />
                        </div>
                        <div><b>${l.peerName || l.householdName ||
                          'Invitation'}</b>${l.householdName &&
                            l.peerName
                          ? html`
                            <div class="small">${l.householdName}</div>
                          `
                          : null}<div class="small dim">${l.address || ''}${l.fingerprint
                          ? html`${' '}· <code>${l.fingerprint}</code>`
                          : ''}${l.peerVersion
                          ? ` · MoolaKata ${l.peerVersion}`
                          : ''}${l.certificate
                          ? html`${' '}· certificate <code>${l.certificate}</code>`
                          : ''}</div></div>
                      </div>
                    </td>
                    <td>${linkState(l)}${l.syncTotal
                      ? html`
                        <div class="small"
                          data-help="progress">Syncing: up to ${l.syncThrough
                            ? month(l.syncThrough)
                            : '…'} (${size(l.syncBytes)} of ${size(l.syncTotal)})<div style=${{
                            height: '4px',
                            background: 'var(--border)',
                            borderRadius: '2px',
                            marginTop: '3px',
                          }}><div style=${{
                            width: `${Math.round((l.syncBytes / l.syncTotal) * 100)}%`,
                            height: '4px',
                            background: 'var(--accent)',
                            borderRadius: '2px',
                          }}></div></div></div>
                      `
                      : null}${l.lastError
                      ? html`<div class="small dim">${l.lastError}</div>`
                      : null}${l.certificateOffered
                      ? html`<div class="small" data-help="certificate-changed">Its certificate
                        changed to <code>${grouped(l.certificateOffered)}</code>. Compare it with
                        their admin before accepting it.</div>`
                      : null}</td>
                    <td class="small dim">${l.state === 'invited'
                      ? `code valid until ${day(l.codeExpiresAt)}`
                      : l.state === 'requested'
                      ? 'Compare the fingerprint with them before approving.'
                      : ago(l.lastOkAt)}</td>
                    <td class="num">
                      <div style=${{
                        display: 'flex',
                        flexWrap: 'wrap',
                        gap: '4px',
                        justifyContent: 'flex-end',
                      }}>${l.state === 'requested'
                        ? html`
                          <button class="btn sm" onClick=${() =>
                            act.run(l.id, 'end')}>Reject</button> <button class="btn sm primary"
                            onClick=${() => act.run(l.id, 'approve')}>Approve</button>
                        `
                        : html`
                          ${l.certificateOffered
                            ? html`
                              <button class="btn sm primary" disabled=${act.busy} onClick=${() =>
                                act.run(l.id, 'accept-certificate')}>Accept It</button>
                            `
                            : null}${['active', 'pending'].includes(l.state)
                            ? html`
                              <button class="btn sm" disabled=${act.busy} onClick=${() =>
                                act.run(l.id, 'pull')}>Pull Now</button>
                            `
                            : null}${l.state === 'active'
                            ? html`
                              <button class="btn sm" onClick=${() => pause(l)}>Pause…</button>
                            `
                            : l.state === 'paused'
                            ? html`
                              <button class="btn sm" onClick=${() =>
                                act.run(l.id, 'resume')}>Resume Now</button>
                            `
                            : null}<button class="btn sm danger"
                            onClick=${async () => {
                              const invited = l.state === 'invited';
                              if (
                                !(await confirmAction({
                                  title: invited ? 'Withdraw this invitation?' : 'End this link?',
                                }))
                              ) return;
                              act.run(l.id, 'end').catch(() => {});
                            }}>${l.state === 'invited' ? 'Withdraw' : 'End Link'}</button>
                        `}</div>
                    </td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        `
        : html`<${Empty}>No links yet</${Empty}>`}
      ${ended.length
        ? html`<p class="small dim">Ended: ${
          ended.map((/** @type {any} */ l) =>
            `${l.peerName || 'an invitation'} (${day(l.endedAt)})`
          ).join(', ')
        }.</p>`
        : null}
      <${FormError} error=${act.error} />
    </div>
    ${copies(live, values, res.reload, copyAct, release)}
    ${live.filter((/** @type {any} */ l) => l.outgoing.length).map((/** @type {any} */ l) =>
      html`<div class="card mt"><h3 data-help="outgoing">Shared from Here with ${l.peerName}</h3>
        ${
        l.outgoing.map((/** @type {any} */ x) =>
          html`<div class="list-item"><div class="grow"><span class="row-name">${
            KIND[x.kind] || 'An item'
          }</span> <span
            class="row-more">of ${x.ownerName} since ${day(x.sharedAt)}${
            x.includeReceipts ? ', with its receipts' : ''
          }</span></div><span class="small">to ${x.names.join(', ')}</span></div>`
        )
      }</div>`
    )}
    ${live.filter((/** @type {any} */ l) => l.incoming.length).map((/** @type {any} */ l) =>
      html`<div class="card mt"><h3 data-help="incoming">Shared from ${l.peerName}</h3>
        ${
        l.incoming.map((/** @type {any} */ x) =>
          html`<div class="list-item"><div class="grow"><span class="row-name">${
            KIND[x.kind] || 'An item'
          }</span> <span
            class="row-more">shared by ${x.ownerName} on ${day(x.sharedAt)}${
            x
                .includeReceipts
              ? ', with its receipts'
              : ''
          }</span></div><span class="small">with ${
            x.names.join(', ') ||
            'no one here'
          }</span></div>`
        )
      }</div>`
    )}
    <div class="card mt">
      <h3 data-help="linked-users">Users on Linked Servers</h3>
      ${people.length
        ? people.map((/** @type {any} */ l) =>
          html`<div class="small dim" style=${{ margin: '10px 0 2px' }}><${Icon}
            name="server" /> <b>${l.peerName}</b></div>${
            l.users.map((/** @type {any} */ u) =>
              html`
                <div
                  class="list-item">
                  <div class="grow">${u.displayName}<div class="small dim">${u
                    .username}${u.email ? ` · ${u.email}` : ''}</div></div>
                  <${StatePill}
                    why="A user on a linked server: people here can share with them, read only."
                  >remote</${StatePill}></div>
              `
            )
          }`
        )
        : html`<${Empty}>No users on linked servers yet</${Empty}>`}
    </div>
  `;
}

/** @param {{ close: (v?: any) => void }} p */
function InviteLink({ close }) {
  useDialogGuide('dialog-link-invite');
  const [made, setMade] = useState(/** @type {any} */ (null));
  const make = useSubmit(async () => {
    setMade(await api.post('/settings/links/invitations'));
  });
  useEffect(() => {
    make.run().catch(() => {});
  }, []);
  return html`
    <${Dialog} title="Invite a Server to Link" close=${close} onSubmit=${() => close(true)}
      note="It works once, for 24 hours."
      footer=${html`
        <button type="button" class="btn" disabled=${!made} onClick=${() =>
          navigator.clipboard?.writeText(made.code).then(() => toast('Copied'))}>Copy</button>
        <button class="btn primary">Done</button>
      `}>
      ${make.error ? html`<${FormError} error=${make.error} />` : made
        ? html`
          <div class="field"
            data-help="link-code"><code class="mono" style=${{
              display: 'block',
              padding: '10px 12px',
              background: 'var(--bg-3)',
              borderRadius: '8px',
            }}>${made.code}</code></div>
        `
        : html`<${Loading} lines=${2} />`}
    </${Dialog}>
  `;
}

/** @param {{ close: (v?: any) => void }} p */
function JoinLink({ close }) {
  useDialogGuide('dialog-link-join');
  const [code, setCode] = useState('');
  const save = useSubmit(async () => {
    const out = await api.post('/settings/links/join', { code });
    toast(`Asked ${out.peerName || 'the server'} to link`);
    close(out);
  });
  return html`
    <${Dialog} title="Enter a Link Code" close=${close} onSubmit=${() => save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy || !code}>Connect</button>`}>
      <${Field} label="Link code" error=${errAt(save.error, 'code')}>
        <textarea class="in mono" rows="3" value=${code} onInput=${(/** @type {any} */ e) =>
          setCode(e.currentTarget.value)}
          placeholder="ex: mkl1.…"
          spellcheck="false"></textarea>
        </${Field}>
        <${FormError} error=${save.error} shown=${['code']} />
        </${Dialog}>
  `;
}

/** @param {number} n */
const size = (n) =>
  n >= 1048576 ? `${(n / 1048576).toFixed(n >= 10485760 ? 0 : 1)} MB` : `${Math.ceil(n / 1024)} KB`;

/**
 * The Linked copies card (S11.7, S11.9): each copy's access key, size and lock, Create the
 * access key, Lock now and Reset copy, and how long an unused copy stays unlocked.
 * @param {any[]} live @param {any} values @param {() => void} reload @param {any} act
 * @param {any} release
 */
function copies(live, values, reload, act, release) {
  const rows = live.filter((l) => l.linkedCopy);
  return html`
    <div class="card mt">
      <h3 data-help="linked-copies">Linked Copies</h3>
      ${rows.length
        ? html`
          <div class="table-wrap">
            <table class="t">
              <caption class="sr-only">Linked copies</caption>
              <thead>
                <tr>
                  <th>Link</th>
                  <th>Copy</th>
                  <th>Waiting</th>
                  <th>Access Key</th>
                  <th>State</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>${rows.map((l) => {
                const c = l.linkedCopy;
                return html`
                  <tr>
                    <td><b>${l.peerName}</b><div class="small dim">${c.items} item${c.items === 1
                      ? ''
                      : 's'} shared</div></td>
                    <td class="small">${size(c.sizeBytes)}${c.receipts
                      ? ` · ${c.receipts} receipt${c.receipts === 1 ? '' : 's'}`
                      : ''}</td>
                    <td class="small">${c.waiting
                      ? `${c.waiting} change${c.waiting === 1 ? '' : 's'}`
                      : html`<span class="dim">none</span>`}</td>
                    <td class="small">${c.keyMadeAt
                      ? html`${day(c.keyMadeAt)}<div class="dim">by ${
                        c.keyMadeBy || 'an admin'
                      }</div>`
                      : html`<span class="pill warn">not made</span>`}</td>
                    <td class="small">${c.unlocked
                      ? html`<span class="pill info">unlocked</span><div class="dim">by ${c.unlockedBy} · locks in ${
                        Math.ceil((c.locksInSeconds || 0) / 60)
                      } min
                  unused</div>`
                      : html`<span class="pill"><${Icon} name="lock" /> locked</span>`}</td>
                    <td class="num" style=${{ whiteSpace: 'nowrap' }}>${!c.keyMadeAt
                      ? html`<button class="btn sm primary" onClick=${() =>
                        openDialog(CopyKey, { link: l }).then(
                          reload,
                        )}>Create the Access Key</button>`
                      : html`${
                        c.unlocked
                          ? html`
                            <button class="btn sm" onClick=${() =>
                              act.run(l.id, 'lock').catch(() => {})}>Lock Now</button>
                          `
                          : null
                      }<button class="btn sm danger" onClick=${async () => {
                        if (
                          !(await confirmAction({ title: 'Reset This Copy?' }))
                        ) return;
                        act.run(l.id, 'reset-copy').catch(() => {});
                      }}>Reset Copy</button>`}</td>
                  </tr>
                `;
              })}</tbody>
            </table>
          </div>
        `
        : html`<${Empty}>No linked copies yet</${Empty}>`}
      <${Field} label="Release linked keys after" id="link-release">
        <${Select} value=${String(values.linkReleaseMinutes)} onChange=${(
          /** @type {string} */ v,
        ) => release.run(v).catch(() => {})} options=${[
          ['15', '15 minutes unused'],
          ['60', '1 hour unused'],
          ['240', '4 hours unused'],
        ]} />
      </${Field}>
      <${FormError} error=${act.error || release.error} />
    </div>
  `;
}

/** Create the access key (S11.9.2.1): the 12 words, shown once. */
/** @param {{ close: (v?: any) => void, link: any }} p */
function CopyKey({ close, link }) {
  useDialogGuide('dialog-copy-key');
  const [words, setWords] = useState(/** @type {string[] | null} */ (null));
  const [saved, setSaved] = useState(false);
  const make = useSubmit(async () => {
    setWords(
      (await withReauth(() => api.post(`/settings/links/${link.id}/copy-key`))).words,
    );
  });
  useEffect(() => {
    make.run().catch(() => {});
  }, []);
  return html`
    <${Dialog} title=${`Access Key for ${link.peerName}`} close=${close}
      onSubmit=${() => saved && close(true)} note="They are shown once."
      footer=${html`
        <button type="button" class="btn" disabled=${!words} onClick=${() =>
          navigator.clipboard?.writeText((words || []).join(' ')).then(() =>
            toast('Copied')
          )}>Copy</button>
        <button class="btn primary" disabled=${!saved}>Done, Words Saved</button>
      `}>
      ${make.error
        ? html`<${FormError} error=${make.error} />`
        : words
        ? html`<div class="words" data-help="words">${
          words.map((w, i) => html`<div class="word"><span>${i + 1}</span><b>${w}</b></div>`)
        }</div>`
        : html`<${Loading} lines=${3} />`}
      <label class="list-item" style=${{ cursor: 'pointer' }}><input type="checkbox"
        id="f-words-saved" checked=${saved} onChange=${(/** @type {any} */ e) =>
          setSaved(e.currentTarget.checked)} /> <span class="grow">I have saved the 12
          words</span></label>
    </${Dialog}>
  `;
}

/** "July 2022". @param {string} iso */
const month = (iso) =>
  new Date(iso + 'T12:00:00Z').toLocaleString('en-US', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });

/**
 * Pause a link for a duration (S11.7.2, S12.13): it stops pulling and answering, and resumes on
 * its own after it; Resume now ends it early.
 * @param {{ close: (v?: any) => void, link: any }} p
 */
function PauseDialog({ close, link }) {
  useDialogGuide('dialog-link-pause');
  // Empty until a duration is typed or ↺ fills in the default (S11.7.2, R3.11).
  const [span, setSpan] = useState('');
  const go = useSubmit(async () => {
    const out = await api.post(`/settings/links/${link.id}/pause`, { for: span });
    toast(`Paused until ${moment(out.pausedUntil)}`);
    close(out);
  });
  const parsed = parseDuration(span);
  const minutes = 'minutes' in parsed ? parsed.minutes : 0;
  return html`
    <${Dialog} title=${`Pause the Link with ${link.peerName || 'the other server'}`} close=${close}
      onSubmit=${() => go.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${go.busy}>Pause</button>`}>
      <${Field} label="Pause for" id="pause-for" error=${errAt(go.error, 'for')}
        hint=${minutes
          ? `Resumes on its own ${moment(new Date(Date.now() + minutes * 60000).toISOString())}.`
          : null}>
        <${TypedInput} kind="duration" value=${span} onInput=${setSpan}
          reset=${{ value: '1d', label: '1 day' }} placeholder="ex: 1d 4h" />
        </${Field}>
        <${FormError} error=${go.error} shown=${['for']} />
        </${Dialog}>
  `;
}
