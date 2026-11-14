// Profile (requirements S12.2.16): name, sex, birthday and relationships (S10.10), email,
// avatar, password, two-step sign-in (S10.1.6), time zone, theme and alert emails.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { date } from '../kit/format.js';
import { useApi, useSubmit } from '../app/hooks.js';
import { useTitle } from '../components/frame.js';
import { Avatar, Failed, Loading } from '../kit/bits.js';
import { errAt, Field, FormError, Input, Select, TypedInput } from '../kit/fields.js';
import { toast } from '../kit/toast.js';
import { Dialog, openDialog } from '../kit/dialog.js';
import { ModelsChart } from '../charts/chart.js';
import { useDialogGuide, useGuide } from '../components/help.js';
import { applyTheme, theme } from '../store/prefs.js';
import { loadSession, session } from '../store/session.js';
import { AccessTokens } from '../components/tokens.js';
import { Connections } from '../components/connections.js';
import { num } from '../kit/dec.js';
import { Record as Rec } from '../app/draft.js';
import { DraftForm, RecField, saveNow, useDraft } from '../components/draft-form.js';
import { asFields, DAY } from './gifts.js';
import { FIELDS } from '../api/fields.js';
import { confirmAction } from '../kit/confirm.js';
import { Attention, Empty, RowTool, StatePill } from '../kit/state.js';

/** The user's own assumptions (S6.3), as their form's draft edits them. */
class AsmRec extends Rec {
  /** @override */
  static prefix = 'Asmpt';
  /** @override */
  static fields = FIELDS.AssumptionsRecord;
}

/** The user's own record (S12.2.16), as Profile's draft edits it. */
class ProfileRec extends Rec {
  /** @override */
  static prefix = 'User';
  /** @override */
  static fields = FIELDS.UserRecord;
}

/** A birthday typed as one field, kept as its person's month, day and year. */
const readBirthday = (/** @type {string} */ t) => {
  const r = DAY.read(t);
  return 'error' in r ? r : { value: asFields(r.value, 'birth') };
};

export default function Profile() {
  useTitle('Profile');
  useGuide('profile');
  const res = useApi('/profile');
  const zones = useApi('/timezones');
  const p = /** @type {any} */ (res.data);
  const fd = useDraft((draft) => {
    if (p) draft.load(ProfileRec, p);
  }, [p?.id, p?.version]);
  const rec = /** @type {ProfileRec | undefined} */ (fd.draft?.records[0]);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!p || !rec) return html`<${Loading} lines=${8} />`;
  const z = /** @type {any} */ (zones.data);
  const pickAvatar = (/** @type {any} */ ev) => {
    const file = ev.currentTarget.files?.[0];
    if (!file) return;
    const img = new Image();
    img.onload = () => {
      // Made small in the browser: a 128-pixel square.
      const c = document.createElement('canvas');
      c.width = c.height = 128;
      const side = Math.min(img.width, img.height);
      c.getContext('2d')?.drawImage(
        img,
        (img.width - side) / 2,
        (img.height - side) / 2,
        side,
        side,
        0,
        0,
        128,
        128,
      );
      rec.set('avatar', c.toDataURL('image/webp', 0.85));
      URL.revokeObjectURL(img.src);
    };
    img.src = URL.createObjectURL(file);
  };
  const birthday = rec.typed('birthday') ??
    DAY.show(rec.get('birthYear'), rec.get('birthMonth'), rec.get('birthDay'));
  return html`
    <div class="grid g2">
      <${DraftForm} f=${fd} class="card" where="Profile" what="Your profile"
        saved=${() => {
          theme.value = rec.get('theme');
          applyTheme();
          toast('Saved');
          res.reload();
          loadSession();
        }}><h3>Profile</h3>
          <div class="acct-row" style=${{ marginBottom: '14px' }}><${Avatar} name=${rec.get(
            'displayName',
          )} image=${rec.get('avatar')} id=${p.id} />
            <label class="btn sm" for="f-avatar">Change avatar</label>
            <input id="f-avatar" class="sr-only" type="file" accept="image/png,image/jpeg,image/webp" onChange=${pickAvatar} />
            ${rec.get('avatar')
              ? html`<button type="button" class="btn sm" onClick=${() =>
                rec.set('avatar', null)}>Remove</button>`
              : null}</div>
          ${rec.error('avatar') ? html`<div class="err">${rec.error('avatar')}</div>` : null}
          <${RecField} rec=${rec} name="displayName" label="Display name" />
          <${RecField} rec=${rec} name="timeZone" label="Time zone"
            options=${[[
              'auto',
              `Auto: the server's (${z?.server || '…'})`,
            ], ...(z?.zones || []).map((/** @type {string} */ x) => [x, x])]} />
          <${RecField} rec=${rec} name="theme" label="Theme" options=${[['dark', 'Dark'], [
            'light',
            'Light',
          ], ['system', "The system's"]]} />
          <div class="row">
            <${RecField} rec=${rec} name="sex" label="Sex" options=${[['female', 'Female'], [
              'male',
              'Male',
            ]]} />
            <${Field} label="Birthday" error=${rec.error('birthday') || rec.error('birthDay') ||
              rec.error('birthMonth') || rec.error('birthYear')}><${Input}
              value=${birthday} placeholder="YYYY-MM-DD" onInput=${(/** @type {string} */ v) =>
                rec.inputAs('birthday', v, readBirthday)} /></${Field}>
          </div>
          <${RecField} rec=${rec} name="alertEmails" label="Alert emails" options=${[
            ['each', 'Each alert'],
            ['daily', 'A daily summary'],
            ['none', 'None'],
          ]} />
          <${RecField} rec=${rec} name="bitcoinUnit" label="Bitcoin in" id="bitcoin-unit"
            options=${[
              ['btc', 'BTC: 0.12345678 BTC'],
              ['sats', 'Sats: 12,345,678 sats'],
            ]} />
        </${DraftForm}>
        <div class="grid" style=${{ alignContent: 'start' }}>
          <${Relations} p=${p} reload=${res.reload} />
          <${Email} p=${p} reload=${res.reload} />
          <${Password} />
          <${TwoStep} p=${p} reload=${res.reload} />
          <${Connections} />
          <${AccessTokens} />
          <${IgnoredLines} />
        </div></div>
      <${Assumptions} />
  `;
}

/** Who the user is related to (S10.10.6): those entered, with their dates, and those worked
 * out from them. */
/** @param {{ p: any, reload: () => void }} props */
function Relations({ p, reload }) {
  const rels = useApi('/relationships', {});
  const rows = /** @type {any[]} */ ((/** @type {any} */ (rels.data))?.items || []);
  const again = () => {
    rels.reload();
    reload();
  };
  // A relationship's row shows the whole of it: one who only reads it has nothing more to
  // see, so no tool (S12.19.5).
  const open = (/** @type {any} */ r) =>
    openDialog(RelationshipDialog, { me: p.personId, r }).then((x) => x && again());
  // A marriage counts for wash sales and tax books once both have confirmed it (S10.10.4).
  const confirm = async (/** @type {any} */ r) => {
    try {
      await api.post(`/relationships/${r.id}/confirm`);
      toast('Confirmed');
      again();
    } catch (e) {
      toast(/** @type {any} */ (e).message);
    }
  };
  const worked = p.relations.filter((/** @type {any} */ r) => !r.stored);
  const word = (/** @type {any} */ r) =>
    (p.relations.find((/** @type {any} */ x) => x.stored && x.personId === other(r))?.word) ||
    (r.relation === 'family' && r.label) || r.relation;
  const other = (/** @type {any} */ r) => r.person1.id === p.personId ? r.person2.id : r.person1.id;
  const name = (/** @type {any} */ r) =>
    r.person1.id === p.personId ? r.person2.name : r.person1.name;
  return html`
    <div class="card" data-help="relationships"><h3>Relationships<span class="spacer"></span><button
      type="button" class="btn sm" onClick=${() => open(null)}>Add</button></h3>
      ${rows.length
        ? rows.map((/** @type {any} */ r) =>
          html`
            <div class="list-item">
              <div class="grow"><span class="row-name">${name(
                r,
              )}</span> <span class="row-more">· ${word(
                r,
              )}</span>${relDates(r)
                ? html`<div class="row-more">${relDates(r)}</div>`
                : null}${confirmation(r)}</div>
              ${r.canConfirm
                ? html`<button type="button" class="btn sm primary" onClick=${(
                  /** @type {Event} */ ev,
                ) => {
                  ev.stopPropagation();
                  confirm(r);
                }}>Confirm</button>`
                : null}
              ${r.access.writable
                ? html`<${RowTool} name=${`${name(r)}, ${word(r)}`} onClick=${() => open(r)} />`
                : null}
            </div>
          `
        )
        : html`<${Empty}>None yet</${Empty}>`}
      ${worked.length
        ? html`<h4 style=${{ margin: '10px 0 4px' }}>Worked Out from These</h4>
          ${
          worked.map((/** @type {any} */ r) =>
            html`
              <div class="list-item">
                <div
                  class="grow"><span class="row-name">${r.name}</span> <span class="row-more">· ${r
                    .word}</span></div>
              </div>
            `
          )
        }`
        : null}
    </div>
  `;
}

/** A marriage's confirmations, as a pill (S12.19.3): by both, or whom it waits for. */
const confirmation = (/** @type {any} */ r) => {
  if (r.confirmed === null || r.confirmed === undefined) return null;
  if (r.confirmed) {
    return html`
      <div>
        <${StatePill} tone="ok"
          why="Both have confirmed it: it is used for wash sales and joint tax books.">confirmed</${StatePill}></div>
    `;
  }
  const who = r.waitingFor.map((/** @type {any} */ x) => x.name).join(' and ');
  return html`
    <div>
      <${StatePill} why=${`Waiting for ${who} to confirm: it counts for gifts only until then.`}>waiting</${StatePill}></div>
  `;
};

/** "since Jun 14, 2009", "Jun 14, 2009 – Mar 2, 2015", or how a marriage ended. */
const relDates = (/** @type {any} */ r) => {
  const from = r.fromDate ? date(r.fromDate) : '';
  if (r.endsOn) {
    const why = r.relation === 'spouse' && !r.toDate ? ' (widowed)' : '';
    return `${from || 'until'}${from ? ' – ' : ' '}${date(r.endsOn)}${why}`;
  }
  return from ? `since ${from}` : '';
};

const KINDS = /** @type {[string, string][]} */ ([
  ['spouse', 'Spouse of'],
  ['couple', 'Couple with'],
  ['parent-of', 'Parent of'],
  ['child-of', 'Child of'],
  ['friend', 'Friend of'],
  ['colleague', 'Colleague of'],
  ['family', 'Family of'],
]);

/** A relationship (S10.10.4), as a draft makes, changes or removes it. */
class RelRec extends Rec {
  /** @override */
  static prefix = 'Rltn';
  /** @override */
  static fields = FIELDS.RelationshipRecord;
}

/** A relationship as read, in its record's fields. @param {any} r */
const stored = (r) => ({
  id: r.id,
  version: r.version,
  person1Id: r.person1.id,
  person2Id: r.person2.id,
  relation: r.relation,
  label: r.label,
  fromDate: r.fromDate,
  toDate: r.toDate,
});

/** @param {{ close: (v?: any) => void, me: string, r: any }} props */
function RelationshipDialog({ close, me, r }) {
  useDialogGuide('dialog-relationship');
  const persons = useApi('/persons');
  const admin = !!session.value?.user?.admin;
  // A stored relationship, read from the side of the first person shown.
  const start = () => {
    if (!r) return { who: me, relation: 'spouse', other: '', fromDate: '', toDate: '', label: '' };
    const who = r.person1.id === me || r.person2.id === me ? me : r.person1.id;
    const otherId = who === r.person1.id ? r.person2.id : r.person1.id;
    const relation = r.relation === 'child'
      ? (r.person1.id === who ? 'parent-of' : 'child-of')
      : r.relation;
    return {
      who,
      relation,
      other: otherId,
      fromDate: r.fromDate || '',
      toDate: r.toDate || '',
      label: r.label || '',
    };
  };
  const [f, setF] = useState(start);
  const [was] = useState(() => JSON.stringify(f));
  const set = (/** @type {string} */ k) => (/** @type {any} */ v) => setF({ ...f, [k]: v });
  const save = useSubmit(async () => {
    // "Child of" runs from the other person to the first; the rest from the first.
    const [kind, first] = f.relation === 'child-of'
      ? ['child', false]
      : f.relation === 'parent-of'
      ? ['child', true]
      : [f.relation, true];
    const body = {
      person1Id: first ? f.who : f.other,
      person2Id: first ? f.other : f.who,
      relation: kind,
      label: f.label || null,
      fromDate: f.fromDate || null,
      toDate: f.toDate || null,
    };
    await saveNow((d) => {
      if (!r) return void d.add(RelRec, body);
      const rec = d.load(RelRec, stored(r));
      for (const [k, v] of Object.entries(body)) rec.set(k, v);
    });
    toast('Saved');
    close(true);
  });
  const remove = useSubmit(async () => {
    await saveNow((d) => d.remove(d.load(RelRec, stored(r))));
    toast('Relationship removed');
    close(true);
  });
  const e = save.error || remove.error;
  const all = /** @type {any[]} */ ((/** @type {any} */ (persons.data))?.items || []);
  const list = all.filter((/** @type {any} */ x) => x.id !== f.who);
  return html`
    <${Dialog} title=${r ? 'A Relationship' : 'Add a Relationship'} close=${close} onSubmit=${() =>
      save.run().catch(
        () => {},
      )} changed=${() => JSON.stringify(f) !== was}
      footer=${html`${
        r
          ? html`
            <button type="button" class="btn danger" disabled=${remove.busy}
              onClick=${async () => {
                const sure = await confirmAction({
                  title: 'Remove This Relationship?',
                });
                if (sure) remove.run().catch(() => {});
              }}>Remove</button><span class="spacer"
            ></span>
          `
          : null
      }<button class="btn primary" disabled=${save.busy}>${r ? 'Save' : 'Add'}</button>`}>
      ${admin
        ? html`
          <${Field} label="Person" id="person"
            error=${errAt(e, 'person1Id')}>
            <${Select} value=${f.who} onChange=${set('who')} options=${all.map((
              /** @type {any} */ x,
            ) => [x.id, x.id === me ? `${x.name} (you)` : x.name])} />
            </${Field}>
        `
        : null}
      <div class="row">
        <${Field} label=${f.who === me ? 'I am the' : 'They are the'} id="relation"
          error=${errAt(e, 'relation')}>
          <${Select} value=${f.relation} onChange=${set('relation')} options=${KINDS} />
        </${Field}>
        <${Field} label="Other person" id="other-person" error=${errAt(e, 'person2Id') ||
          errAt(e, 'person1Id')}>
          <${Select} value=${f.other} onChange=${set('other')} options=${[
            ['', 'Choose…'],
            ...list.map((/** @type {any} */ x) => [x.id, x.name]),
          ]} />
        </${Field}>
      </div>
      <div class="row">
        <${Field} label="From" id="from-date" error=${errAt(e, 'fromDate')}>
          <${TypedInput} kind="date" value=${f.fromDate} onInput=${set('fromDate')} />
        </${Field}>
        <${Field} label="To" id="to-date" error=${errAt(e, 'toDate')}>
          <${TypedInput} kind="date" value=${f.toDate} onInput=${set('toDate')}
            placeholder="still holds" />
        </${Field}>
        <${Field} label="Label" error=${errAt(e, 'label')}>
          <${Input} value=${f.label} onInput=${set('label')} />
        </${Field}>
      </div>
      <${FormError} error=${e} shown=${[
        'relation',
        'person1Id',
        'person2Id',
        'fromDate',
        'toDate',
        'label',
      ]} />
    </${Dialog}>
  `;
}

/** @param {{ p: any, reload: () => void }} props */
function Email({ p, reload }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [needPassword, setNeed] = useState(false);
  const save = useSubmit(async () => {
    if (needPassword) await api.post('/session/reauth', { password });
    try {
      await api.post('/profile/email', { email });
    } catch (e) {
      if (/** @type {any} */ (e).code === 'reauth-required') {
        setNeed(true);
        return;
      }
      throw e;
    }
    toast(`A confirmation link went to ${email}`);
    setEmail('');
    setNeed(false);
    reload();
  });
  return html`
    <form class="card" onSubmit=${(/** @type {Event} */ ev) => {
      ev.preventDefault();
      save.run().catch(() => {});
    }}>
      <h3>Email Address</h3>
      <p class="small" style=${{ marginTop: 0 }}>${p.email}${p.pendingEmail
        ? html`<span class="dim"> · waiting for ${p.pendingEmail} to be confirmed</span>`
        : null}</p>
      <${Field} label="New email address" error=${errAt(save.error, 'email')}>
          <${Input} type="email" value=${email} onInput=${setEmail} autocomplete="email" required /></${Field}>
        ${needPassword
          ? html`
            <${Field} label="Your password" id="reauth-password">
              <${Input}
                type="password" value=${password} onInput=${setPassword} autocomplete="current-password"
                required />
              </${Field}>
          `
          : null}
        <${FormError} error=${save.error} shown=${['email']} />
        <button class="btn" disabled=${save.busy}>Send the Confirmation Link</button></form>
  `;
}

function Password() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const save = useSubmit(async () => {
    await api.post('/profile/password', { currentPassword: current, newPassword: next });
    toast('Password changed: your other sessions were signed out');
    setCurrent('');
    setNext('');
  });
  return html`
    <form class="card" onSubmit=${(/** @type {Event} */ ev) => {
      ev.preventDefault();
      save.run().catch(() => {});
    }}>
      <h3>Password</h3>
      <${Field} label="Current password" error=${errAt(save.error, 'currentPassword')}>
        <${Input} type="password" value=${current}
          onInput=${setCurrent} autocomplete="current-password" required />
        </${Field}>
        <${Field} label="New password" error=${errAt(save.error, 'newPassword')}>
          <${Input} type="password" value=${next} onInput=${setNext} autocomplete="new-password" required /></${Field}>
        <${FormError} error=${save.error} shown=${['currentPassword', 'newPassword']} />
        <button class="btn" disabled=${save.busy}>Change Password</button></form>
  `;
}

/**
 * Two-step sign-in: off, or on with the recovery codes left. Each change asks for the
 * password again when it was given over 10 minutes ago (S13.7.2).
 * @param {{ p: any, reload: () => void }} props
 */
function TwoStep({ p, reload }) {
  const [password, setPassword] = useState('');
  const [needPassword, setNeed] = useState(false);
  const act = useSubmit(async (/** @type {() => Promise<void>} */ fn) => {
    if (needPassword) await api.post('/session/reauth', { password });
    try {
      await fn();
    } catch (e) {
      if (/** @type {any} */ (e).code === 'reauth-required') {
        setNeed(true);
        return;
      }
      throw e;
    }
    setNeed(false);
    setPassword('');
  });
  const turnOn = async () => {
    const setup = await api.post('/profile/two-step');
    const done = await openDialog(TwoStepSetup, { setup });
    if (done) toast('Two-step sign-in is on');
    reload();
  };
  const newCodes = async () => {
    const r = await api.post('/profile/two-step/recovery-codes');
    await openDialog(RecoveryCodes, { codes: r.codes, fresh: true });
    reload();
  };
  const turnOff = async () => {
    await api.post('/profile/two-step/off');
    toast('Two-step sign-in is off');
    reload();
  };
  const run = (/** @type {() => Promise<void>} */ fn) => act.run(fn).catch(() => {});
  const ts = p.twoStep;
  return html`
    <div class="card" id="two-step">
      <h3>Two-Step Sign-In ${ts.on
        ? html`<span class="pill ok">on</span>`
        : html`<span class="pill">off</span>`}</h3>
      ${ts.on
        ? html`<p class="small dim" style=${{ marginTop: 0 }}>${ts.recoveryCodesLeft} recovery
          code${ts.recoveryCodesLeft === 1 ? '' : 's'} left.</p>`
        : null}
      ${ts.on && ts.recoveryCodesLeft <= 3
        ? html`
          <${StatePill} tone="warn"
            why="Recovery codes left: make new ones before they run out.">${ts
              .recoveryCodesLeft} code${ts.recoveryCodesLeft === 1 ? '' : 's'} left</${StatePill}>
        `
        : null}
      ${needPassword
        ? html`
          <${Field} label="Your password" id="two-step-password">
            <${Input} type="password" value=${password} onInput=${setPassword}
              autocomplete="current-password" required />
            </${Field}>
        `
        : null}
      <${FormError} error=${act.error} />
      ${ts.on
        ? html`
          <button type="button" class="btn" disabled=${act.busy}
            onClick=${() =>
              run(newCodes)}>New Recovery Codes</button> <button type="button" class="btn danger"
            disabled=${act.busy} onClick=${() => run(turnOff)}>Turn Off</button>
        `
        : html`<button type="button" class="btn" disabled=${act.busy} onClick=${() =>
          run(turnOn)}>Turn On</button>`}
    </div>
  `;
}

/**
 * Setting up: the QR code (or the key, typed by hand), then a code from the app to confirm,
 * then the recovery codes, shown once.
 * @param {{ close: (v?: any) => void, setup: { secret: string, uri: string, qrImage: string } }} props
 */
function TwoStepSetup({ close, setup }) {
  useDialogGuide('dialog-two-step');
  const [code, setCode] = useState('');
  const [codes, setCodes] = useState(/** @type {string[] | null} */ (null));
  const save = useSubmit(async () => {
    const r = await api.post('/profile/two-step/confirm', { code });
    setCodes(r.codes);
  });
  if (codes) {
    return html`<${RecoveryCodes} close=${() => close(true)} codes=${codes} fresh=${false} />`;
  }
  const key = setup.secret.replace(/(.{4})/g, '$1 ').trim();
  return html`
    <${Dialog} title="Turn On Two-Step Sign-In" close=${close}
      onSubmit=${() => save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Turn On</button>`}>
      <div class="qr"><img src=${setup.qrImage} width="180" height="180"
        alt="QR code for your authenticator app" /></div>
      <p class="small center"><span class="dim">Key:</span> <code class="key">${key}</code></p>
      <${Field} label="Code from the app" id="two-step-code" error=${errAt(save.error, 'code')}>
        <${Input} value=${code} onInput=${setCode} inputmode="numeric"
          autocomplete="one-time-code" maxlength="7" required />
        </${Field}>
        <${FormError} error=${save.error} shown=${['code']} />
        </${Dialog}>
  `;
}

/**
 * The ten recovery codes, shown once: each signs in once in place of a code from the app.
 * @param {{ close: (v?: any) => void, codes: string[], fresh: boolean }} props
 */
function RecoveryCodes({ close, codes, fresh }) {
  useDialogGuide('dialog-recovery-codes');
  const text = codes.join('\n') + '\n';
  return html`
    <${Dialog} title=${fresh ? 'New Recovery Codes' : 'Two-Step Sign-In Is On'} close=${close}
      onSubmit=${() => close(true)}
      note="They won't be shown again."
      footer=${html`
        <button type="button" class="btn" onClick=${() =>
          navigator.clipboard?.writeText(text).then(() => toast('Copied'))}>Copy</button>
        <a class="btn" download="moolakata-recovery-codes.txt"
          href=${'data:text/plain;charset=utf-8,' + encodeURIComponent(text)}>Download</a>
        <button class="btn primary">I've Saved Them</button>
      `}>
      ${fresh ? html`<${Attention}>The old ones no longer work.</${Attention}>` : null}
      <ul class="codes">${codes.map((c) => html`<li><code>${c}</code></li>`)}</ul>
      </${Dialog}>
  `;
}

/**
 * Assumptions (S6.3): the expected return and volatility of each asset class, inflation, and
 * the bitcoin model, shared by every projection of yours unless one overrides a figure.
 */
function Assumptions() {
  const res = useApi('/assumptions');
  const v = /** @type {any} */ (res.data);
  // The shipped figures until the user changes one: then their own are made (S6.3).
  const fd = useDraft((draft) => {
    if (!v) return;
    if (v.id) draft.load(AsmRec, v);
    else draft.add(AsmRec, { figures: v.figures }, { optional: true });
  }, [v?.id, v?.version]);
  const rec = /** @type {AsmRec | undefined} */ (fd.draft?.records[0]);
  if (!v || !rec) return null;
  const f = rec.get('figures');
  const setF = (/** @type {any} */ next) => rec.set('figures', next);
  const err = (/** @type {string} */ k) => rec.error(`figures.${k}`);
  const setClass = (/** @type {string} */ k, /** @type {string} */ field) =>
  (
    /** @type {string} */ x,
  ) => {
    const next = structuredClone(f);
    next.classes[k][field] = x === '' ? null : Number(x);
    setF(next);
  };
  return html`
    <${DraftForm} f=${fd} class="card mt" where="Assumptions" what="Your assumptions"
      saved=${() => {
        toast('Saved · projections recompute when opened');
        res.reload();
      }} extra=${() =>
        html`<button type="button" class="linklike" onClick=${() =>
          openDialog(BitcoinModels, {})}>Compare models</button>`}>
      <h3>Assumptions</h3>
      <table class="t">
        <thead>
          <tr>
            <th>Asset Class</th>
            <th class="num">Expected Return %</th>
            <th
              class="num">Volatility %</th>
          </tr>
        </thead>
        <tbody>${v.classes.map(([k, label]) =>
          html`
            <tr>
              <td>${label}</td>
              <td class="num"><input class="in num" style=${{
                maxWidth: '90px',
              }} data-help="expected-return"
                          aria-label=${label + ' expected return'} value=${f.classes[k].return ??
                            ''}
                          onInput=${(/** @type {any} */ ev) =>
                            setClass(k, 'return')(ev.currentTarget.value)} />${err(
                              `classes.${k}.return`,
                            )
                            ? html`<div class="err">${err(`classes.${k}.return`)}</div>`
                            : null}</td>
              <td class="num"><input class="in num" style=${{
                maxWidth: '90px',
              }} data-help="volatility"
                          aria-label=${label + ' volatility'} value=${f.classes[k].volatility ?? ''}
                          onInput=${(/** @type {any} */ ev) =>
                            setClass(k, 'volatility')(ev.currentTarget.value)} />${err(
                              `classes.${k}.volatility`,
                            )
                            ? html`<div class="err">${err(`classes.${k}.volatility`)}</div>`
                            : null}</td>
            </tr>
          `
        )}</tbody>
      </table>
      <div class="row mt">
        <${Field} label="General inflation (%)" id="general-inflation" error=${err('inflation')}>
          <${TypedInput} kind="quantity" value=${f.inflation} onInput=${(/** @type {string} */ x) =>
            setF({ ...f, inflation: Number(x) })} />
          </${Field}>
          <${Field} label="Education inflation (%)" id="education-inflation"
            error=${err('educationInflation')}>
            <${TypedInput} kind="quantity" value=${f.educationInflation} onInput=${(
              /** @type {string} */ x,
            ) => setF({ ...f, educationInflation: Number(x) })} />
            </${Field}>
            </div>
            <${Field} label="Bitcoin model" id="bitcoin-model">
              <${Select} value=${f.bitcoinModel} onChange=${(/** @type {string} */ x) =>
                setF({ ...f, bitcoinModel: x })} options=${v.bitcoinModels} />
              </${Field}>
              </${DraftForm}>
  `;
}

const MODEL_NAMES = /** @type {Record<string, string>} */ ({
  powerLaw: 'Power law',
  logRegression: 'Log regression',
  stockToFlow: 'Stock-to-flow',
  saylor: 'Saylor base',
  ark: 'ARK base',
});

/** Compare models (S6.3.1.1): their median paths and figures, with their sources and records. */
function BitcoinModels({ close }) {
  useDialogGuide('dialog-bitcoin-models');
  const res = useApi('/bitcoin-models');
  const v = /** @type {any} */ (res.data);
  const fmt = (/** @type {any} */ x, n = num(x)) =>
    n >= 1e9
      ? `$${(n / 1e9).toFixed(1)}B`
      : n >= 1e6
      ? `$${(n / 1e6).toFixed(1)}M`
      : `$${Math.round(n / 1e3)}K`;
  return html`
    <${Dialog} title="Bitcoin Models" wide close=${close} footer=${html`
      <button type="button"
        class="btn" onClick=${() => close()}>Close</button>
    `}>
      ${v
        ? html`
          ${v.price
            ? html`<p class="small dim" style=${{ marginTop: 0 }}>Today's price: ${
              fmt(v.price)
            }</p>`
            : null}
          <${ModelsChart} rows=${v.rows} names=${MODEL_NAMES} />
          <div class="table-wrap mt">
            <table class="t">
              <thead>
                <tr>
                  <th>Model</th>
                  <th class="num">2030</th>
                  <th class="num">2035</th>
                  <th class="num">2045</th>
                  <th>Source and Record</th>
                </tr>
              </thead>
              <tbody>${v.rows.map((/** @type {any} */ r) =>
                html`<tr><td>${MODEL_NAMES[r.model]}</td>${
                  [2030, 2035, 2045].map((y) => html`<td class="num">${fmt(r.at[y])}</td>`)
                }<td class="small dim">${r.record}</td></tr>`
              )}</tbody>
            </table>
          </div>
          <p class="small dim">Figures of ${v.figuresYear}</p>
        `
        : html`<p class="dim">Loading…</p>`}
    </${Dialog}>
  `;
}

/** The statement lines this person asked to ignore, by institution (S1.3.3.4). */
function IgnoredLines() {
  const res = useApi('/statement-layouts/ignored', {});
  const rows = /** @type {any[]} */ ((/** @type {any} */ (res.data))?.items || []);
  const remove = async (/** @type {any} */ x) => {
    const sure = await confirmAction({
      title: `Stop Ignoring Lines Starting “${x.start}”?`,
      detail: `They are read again from ${x.institution}'s next statement.`,
    });
    if (!sure) return;
    try {
      await api.post('/statement-layouts/ignored/forget', x);
      toast(`Lines starting “${x.start}” are read again`);
      res.reload();
    } catch (e) {
      toast(/** @type {any} */ (e).message);
    }
  };
  return html`
    <div class="card" data-help="ignored-statement-lines"><h3>Ignored Statement Lines</h3>
      ${rows.length
        ? rows.map((x) =>
          html`
            <div
              class="list-item"><div class="grow">“${x.start}”<div class="small dim">${x
                .institution} · ${x.kind === 'bank'
                ? 'bank and card statements'
                : 'brokerage statements'}</div></div><button type="button" class="btn sm"
              onClick=${() => remove(x)}>Remove</button></div>
          `
        )
        : html`<${Empty}>None</${Empty}>`}
    </div>
  `;
}
