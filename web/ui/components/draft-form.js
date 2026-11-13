// The shared form pieces (requirements S12.15, S17.3.9.6): a form is its fields and nothing
// more. useDraft reads a form's records into a draft, and reads them again after a 412;
// DraftDialog and DraftForm ask before discarding changes, save, then save anyway or reload,
// and show what a save came to above the buttons; RecField draws one field of a record by its
// type.
import { useContext, useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { html } from '../app/html.js';
import { useSubmit } from '../app/hooks.js';
import { api } from '../api/client.js';
import { Draft, READ_ONLY } from '../app/draft.js';
import { Dialog, openDialog } from './dialog.js';
import { guardForm } from '../app/guard.js';
import {
  Field,
  FormError,
  Input,
  OnRow,
  Reads,
  ReadValue,
  Select,
  Switch,
  TypedInput,
  useReading,
} from './fields.js';
import { Action } from './state.js';
import { Failed, Loading } from './bits.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';

/**
 * A form's draft: `load(draft)` reads its records into a new draft, on the first draw, when
 * `deps` change, and on `reload` (after a 412, S12.15.5), which drops the changes made.
 * @param {(draft: Draft) => Promise<any> | any} load
 * @param {any[]} [deps]
 * `post` sends the save elsewhere than the save's route: Settings' keys, which are no record
 * of the save's (S12.15).
 * @param {{ newId?: (prefix: string) => string,
 *   post?: (body: any, key: string) => Promise<any> }} [o]
 * @returns {{ draft: Draft | null, error: any, reload: () => void }}
 */
export function useDraft(load, deps = [], o = {}) {
  const [state, setState] = useState(
    /** @type {{ draft: Draft | null, error: any }} */ ({ draft: null, error: null }),
  );
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    let live = true;
    const draft = new Draft({
      ...(o.newId ? { newId: o.newId } : {}),
      ...(o.post ? { post: o.post } : {}),
    });
    setState({ draft: null, error: null });
    Promise.resolve(loadRef.current(draft)).then(
      () => {
        // What the form starts with is unchanged, the new records an Add dialog makes too.
        draft.settle();
        if (live) setState({ draft, error: null });
      },
      (error) => live && setState({ draft: null, error }),
    );
    return () => {
      live = false;
    };
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}

/**
 * Saving a draft: what the last save came to, kept with the changes it was for, so a question
 * is confirmed only for the changes it was asked about (S12.15.4).
 * @param {Draft | null} draft
 * @param {{ before?: () => boolean | void, saved: (o: any) => void }} o
 */
function useSave(draft, o) {
  const [last, setLast] = useState(/** @type {{ outcome: any, at: string } | null} */ (null));
  const at = () => (draft ? draft.fingerprint() : '');
  // An answer stands while the draft holds what was sent; a refusal stays at its fields.
  const outcome = last && (last.outcome.status !== 'asks' || last.at === at())
    ? last.outcome
    : null;
  const save = useSubmit(async () => {
    if (!draft) return;
    if (o.before?.() === false) return;
    const confirmAsks = last?.outcome.status === 'asks' && last.at === at();
    const r = await draft.save({ confirmAsks });
    setLast({ outcome: r, at: at() });
    if (r.status === 'saved') o.saved(r);
    return r;
  });
  return { save, outcome, clear: () => setLast(null) };
}

/**
 * What a save came to, above the buttons: its questions, listed together; a record changed
 * meanwhile; a refusal that belongs to no field (S12.15.4, S12.15.5).
 * `again` saves again once the password is given anew, for a save that needs it (S13.7.2).
 * @param {{ outcome: any, draft: Draft | null, what: string, again?: () => void }} p
 */
export function SaveOutcome({ outcome, draft, what, again }) {
  if (outcome?.status === 'refused' && draft?.reauth && again) {
    return html`<${Reauth} again=${again} />`;
  }
  if (outcome?.status === 'asks') {
    return html`
      <div class="notice warn" role="alert">
        <${Icon} name="alert" />
        <div>Saving this asks ${outcome.asks.length === 1 ? 'one thing' : 'these'} first:<ol
            class="asks">${outcome.asks.map((/** @type {any} */ a) =>
              html`<li>${a.message}</li>`
            )}</ol></div>
      </div>
    `;
  }
  if (outcome?.status === 'stale') {
    return html`
      <div class="notice warn" role="alert">
        <${Icon} name="alert" />
        <div>${what} changed since you opened it, so nothing was saved. <b>Reload</b> opens it
          as it stands; what you changed here is lost.</div>
      </div>
    `;
  }
  if (draft?.formError) {
    return html`
      <div class="notice warn" role="alert">
        <${Icon} name="alert" />
        <div>${draft.formError}</div>
      </div>
    `;
  }
  return null;
}

/**
 * The password again, above the buttons, for a save that needs it (S13.7.2): given, the save
 * goes again.
 * @param {{ again: () => void }} p
 */
function Reauth({ again }) {
  const [password, setPassword] = useState('');
  const go = useSubmit(async () => {
    await api.post('/session/reauth', { password });
    setPassword('');
    again();
  });
  return html`
    <div class="notice warn" role="alert">
      <${Icon} name="lock" />
      <div class="grow">
        <div>This needs your password again: it was given over 10 minutes ago.</div>
        <div class="row" style=${{ alignItems: 'end' }}>
          <${Field} label="Your password" id="reauth-password" error=${go.error?.message}>
            <${Input} type="password" value=${password} onInput=${setPassword}
              autocomplete="current-password" />
            </${Field}>
            <button type="button" class="btn sm" style=${{ marginBottom: '14px' }}
              disabled=${go.busy || !password} onClick=${() =>
                go.run().catch(() => {})}>Go on</button>
            </div>
            </div>
            </div>
  `;
}

/**
 * The button that saves, saves anyway once asked, or reloads once stale.
 * @param {{ outcome: any, busy: boolean, ready: boolean, label: string, confirm: string,
 *   reload: () => void, disabled?: boolean }} p
 */
function SaveButton({ outcome, busy, ready, label, confirm, reload, disabled }) {
  if (outcome?.status === 'stale') {
    return html`<button type="button" class="btn primary" onClick=${reload}>Reload</button>`;
  }
  return html`<button class="btn primary" disabled=${busy || !ready || disabled}>${
    outcome?.status === 'asks' ? confirm : label
  }</button>`;
}

/**
 * A dialog that edits a draft (S12.15): Escape, ✕, Cancel or Back ask before discarding its
 * changes; Save sends them, Save anyway confirms the questions asked, Reload reads the records
 * again after a 412. `f` is what `useDraft` gave. `before` runs ahead of a save (false stops
 * it); `changed` replaces the draft's own answer for a dialog that puts its choices into the
 * draft only when it saves. `extra` draws the footer's other buttons, given the save (a
 * Delete removes its record and saves); `saveWhy` shows the save's button off, saying why
 * (S12.19.1); `read` draws every field in it in its read persona (S12.18.6), its Save off
 * for that reason (*Shared with you to read*, or the words it is), leaving out a field with
 * nothing in it and those its row shows (`row`, opened from one).
 * @param {{ f: ReturnType<typeof useDraft>, title: string, close: (v?: any) => void,
 *   what: string, done?: Done, label?: string, confirm?: string, wide?: boolean, note?: any,
 *   before?: () => boolean | void, changed?: () => boolean, disabled?: boolean,
 *   saved?: (o: any) => void, saveWhy?: string | null, read?: boolean | string,
 *   row?: string[],
 *   extra?: (s: { save: any, outcome: any }) => any, children: any }} p
 */
/**
 * @typedef {string | ((draft: any) => string)} Done
 * What a save says once done: words, or words worked out from what was saved, at that moment
 * (Ungroup removes the strategy in the click that saves it, CR3-407).
 */

/** Why a form that reads saves nothing (S12.19.1). @param {boolean | string | undefined} read */
function readWhy(read) {
  return typeof read === 'string' ? read : read ? READ_ONLY : null;
}

/** @param {Done} done @param {any} draft */
function doneText(done, draft) {
  return typeof done === 'function' ? done(draft) : done;
}

export function DraftDialog(p) {
  const { f, close } = p;
  const draft = f.draft;
  // Read, its Save is off for the reading's reason, unless it gives another.
  const saveWhy = p.saveWhy ?? readWhy(p.read);
  // The fields come once the records are read: the first takes the focus then (S12.1.3).
  useEffect(() => {
    if (!draft) return;
    // The dialog on top: one opened over another draws after it (S12.15.7).
    const box = [...document.querySelectorAll('.dialog .body')].at(-1);
    if (!box || box.contains(document.activeElement)) return;
    /** @type {HTMLElement | null} */ (box.querySelector(
      'input:not([type=hidden]):not(:disabled),select:not(:disabled),textarea:not(:disabled)',
    ))?.focus();
  }, [draft]);
  const { save, outcome, clear } = useSave(draft, {
    before: p.before,
    saved: p.saved || ((o) => {
      if (p.done) toast(doneText(p.done, draft));
      close(o.saved);
    }),
  });
  return html`
    <${Dialog} title=${p.title} wide=${p.wide} close=${close} note=${p.note}
      changed=${p.changed || (() => !!draft?.changed)}
      save=${saveWhy ? undefined : () => saveFromQuestion(save)}
      onSubmit=${() => saveWhy || save.run().catch(() => {})}
      footer=${html`
        ${p.extra?.({ save, outcome }) || null}${p.read
          ? html`<button type="button" class="btn" onClick=${() => close()}>Close</button>`
          : null}${saveWhy
          ? html`<${Action} class="btn primary" why=${saveWhy}>${p.label || 'Save'}</${Action}>`
          : html`
            <${SaveButton} outcome=${outcome} busy=${save.busy} ready=${!!draft}
              disabled=${p.disabled} label=${p.label || 'Save'}
              confirm=${p.confirm || 'Save anyway'} reload=${() => {
                clear();
                f.reload();
              }} />
          `}
      `}>
      ${f.error
        ? html`<${Failed} error=${f.error} />`
        : !draft
        ? html`<${Loading} lines=${4} />`
        : html`<${Reads} why=${p.read} row=${p.row}>${p.children}</${Reads}>`}
      <${SaveOutcome} outcome=${outcome} draft=${draft} what=${p.what}
        again=${() => save.run().catch(() => {})} />
      <${FormError} error=${save.error} />
    </${Dialog}>
  `;
}

/**
 * A save asked for from the question before changes are lost: whether it saved. A refusal or
 * a question stays with the form, which shows it (S12.15.6).
 * @param {{ run: () => Promise<any> }} save
 */
export async function saveFromQuestion(save) {
  try {
    return (await save.run())?.status === 'saved';
  } catch {
    return false;
  }
}

/**
 * The question before a screen's form loses its changes (S12.15.6): Keep editing (focused, and
 * what Escape answers), Discard, or Save. Closes with 'discard', 'save' or nothing.
 * `answered` hears the answer as it is given, before the dialog has gone.
 * @param {{ close: (v?: any) => void, where: string, answered?: () => void }} p
 */
export function LeaveDialog({ close, where, answered }) {
  const answer = (/** @type {string | undefined} */ how) => {
    answered?.();
    close(how);
  };
  return html`
    <${Dialog} title="Save your changes?" close=${() => answer(undefined)} footer=${html`
      <button type="button" class="btn" autofocus onClick=${() => answer(undefined)}>Keep
        editing</button>
      <button type="button" class="btn danger" onClick=${() => answer('discard')}>Discard</button>
      <button type="button" class="btn primary" onClick=${() => answer('save')}>Save</button>
    `}>
      <p class="small dim">What you changed in ${where} isn't saved. Save it, or discard it and
        go on.</p>
      </${Dialog}>
  `;
}

/**
 * Asks before a screen's form loses its changes, and saves when told to: whether to go on.
 * @param {string} where @param {() => void} answered @param {() => Promise<boolean>} saveIt
 */
export async function askToLeave(where, answered, saveIt) {
  const how = await openDialog(LeaveDialog, { where, answered });
  if (how === 'discard') return true;
  if (how === 'save') return saveIt();
  return false;
}

/**
 * A screen's form that edits a draft (Settings, Profile; S12.15): its own Save, and while it
 * holds changes, moving elsewhere in the app, Back or leaving the page asks first. `where`
 * names it in the question ("Settings › General").
 * `extra` draws the buttons beside Save, given the save (a Delete removes its record and saves);
 * `class` styles the form (a card). `changed` replaces the draft's own answer (a new record
 * not yet saved is a change, S12.2.3.2.2). `discard`, given, shows Discard and Save only
 * while the form holds changes (S12.2.3.2.1); Discard calls it. `read` draws every field in
 * its read persona (S12.18.6).
 * @param {{ f: ReturnType<typeof useDraft>, where: string, what: string, done?: Done,
 *   read?: boolean | string,
 *   label?: string, confirm?: string, before?: () => boolean | void,
 *   saved?: (o: any) => void, extra?: (s: { save: any, outcome: any }) => any,
 *   changed?: () => boolean, discard?: () => void, class?: string, children: any }} p
 */
export function DraftForm(p) {
  const { f } = p;
  const draft = f.draft;
  const { route } = useLocation();
  const { save, outcome, clear } = useSave(draft, {
    before: p.before,
    saved: p.saved || (() => {
      if (p.done) toast(doneText(p.done, draft));
      f.reload();
    }),
  });
  const has = p.changed || (() => !!draft?.changed);
  const changedRef = useRef(/** @type {() => boolean} */ (() => false));
  changedRef.current = has;
  const saveRef = useRef(save);
  saveRef.current = save;
  useEffect(
    () =>
      guardForm({
        has: () => changedRef.current(),
        where: p.where,
        // The save as it stands when asked: the guard is set once, before the draft loads.
        ask: (where, answered) =>
          askToLeave(where, answered, () => saveFromQuestion(saveRef.current)),
        route,
      }),
    [p.where],
  );
  return html`
    <form class=${p.class || 'draft-form'} onSubmit=${(/** @type {Event} */ e) => {
      e.preventDefault();
      if (!p.read) save.run().catch(() => {});
    }}>
      ${f.error
        ? html`<${Failed} error=${f.error} />`
        : !draft
        ? html`<${Loading} lines=${4} />`
        : html`<${Reads} why=${p.read}>${p.children}</${Reads}>`}
      <${SaveOutcome} outcome=${outcome} draft=${draft} what=${p.what}
        again=${() => save.run().catch(() => {})} />
      <${FormError} error=${save.error} />
      <div class="toolbar mt">
        ${p.extra?.({ save, outcome }) || null}<span class="spacer"></span>
        ${p.read
          ? html`<${Action} class="btn primary" why=${readWhy(p.read)}>${
            p.label ||
            'Save'
          }</${Action}>`
          : p.discard && !has() && outcome?.status !== 'stale'
          ? null
          : html`
            ${p.discard
              ? html`<button type="button" class="btn" onClick=${() => {
                clear();
                p.discard?.();
              }}>Discard</button>`
              : null}
            <${SaveButton} outcome=${outcome} busy=${save.busy} ready=${!!draft}
              label=${p.label || 'Save'} confirm=${p.confirm || 'Save anyway'} reload=${() => {
                clear();
                f.reload();
              }} />
          `}
      </div>
    </form>
  `;
}

/** The typed input (S12.18) for each type a record's field may have. */
const KIND = /** @type {{ [type: string]: string }} */ ({
  money: 'money',
  quantity: 'quantity',
  percent: 'percent',
  int: 'count',
  date: 'date',
});

/**
 * One field of a record, drawn by its type (S17.3.9.6): its kind's typed input for money,
 * quantities, whole numbers and dates (`kind` names another, a web address), a list for a
 * choice or a reference (`options`, as [value, label]), a switch for yes or no; bound to the
 * record: its value, what was typed, its mark and its refusal; hidden while a rule says it
 * doesn't apply. `bare` draws the control alone (a table's cell), named by `label` and `help`.
 * `id` names the control where its label alone wouldn't (`f-` and the id, S12.7.3).
 * `reset` gives a field with a default its ↺, which puts the default back; `min`, `max`
 * (with `noun` for a count), `clear` and `fill` give its other controls (R3.11); `above`, `atMost`
 * and `negative` bound it without one.
 * @param {{ rec: import('../app/draft.js').Record, name: string, label: string, id?: string,
 *   'data-help'?: string, 'aria-invalid'?: string, 'aria-describedby'?: string,
 *   options?: ([string, string] | string)[], hint?: any, help?: string, bare?: boolean,
 *   type?: string, placeholder?: string, disabled?: boolean, onEdit?: () => void,
 *   style?: any, rows?: number, reset?: { value: string, label: string }, kind?: string,
 *   min?: number | string, max?: number | string, above?: number | string,
 *   atMost?: number | string,
 *   negative?: boolean, noun?: string,
 *   format?: (n: any) => string, clear?: boolean, fill?: import('./fields.js').Fill[],
 *   mark?: string | null, readonly?: boolean }} p
 */
export function RecField(p) {
  const { rec, name } = p;
  const reading = useReading(p.readonly);
  const onRow = useContext(OnRow);
  if (!rec.applies(name)) return null;
  // Read, a field its row already shows is left out (S12.18.6.5).
  if (reading && onRow.has(name)) return null;
  const spec = rec.spec(name);
  const error = rec.error(name);
  const edited = () => p.onEdit?.();
  /** @type {any} */
  let control;
  if (spec.type === 'bool') {
    control = html`
      <${Switch} on=${!!rec.get(name)} label=${p.label} help=${p.bare
        ? p.help
        : undefined} disabled=${p.disabled}
        readonly=${reading}
        onChange=${(/** @type {boolean} */ v) => {
          rec.set(name, v);
          edited();
        }} />
    `;
    if (p.bare) return control;
    return html`<div class="list-item"><span class="grow">${p.label}${
      p.hint ? html`<div class="small dim">${p.hint}</div>` : null
    }</span>${control}</div>`;
  }
  // Bare, the control takes what a Field around it gives it: its id, its help, its refusal.
  const named = p.bare
    ? Object.fromEntries(
      Object.entries({
        'aria-label': p.label,
        'data-help': p.help ?? p['data-help'],
        id: p.id,
        'aria-invalid': p['aria-invalid'],
        'aria-describedby': p['aria-describedby'],
      }).filter(([, v]) => v !== undefined),
    )
    : {};
  if (p.options || spec.type === 'choice' || spec.type === 'ref') {
    const options = p.options || (spec.choices || []).map(String);
    control = html`
      <${Select} value=${rec.get(name) ?? ''} options=${options}
        disabled=${p.disabled} readonly=${reading} aria-invalid=${error ? 'true' : undefined}
        ...${named}
        onChange=${(/** @type {string} */ v) => {
          rec.input(name, v);
          edited();
        }} />
    `;
  } else if (p.rows && reading) {
    control = html`<${ReadValue} text=${rec.shown(name) || '—'} rows=${p.rows} ...${named} />`;
  } else if (p.rows) {
    control = html`
      <textarea class="in" rows=${p.rows} disabled=${p.disabled} ...${named}
        onInput=${(/** @type {any} */ e) => {
          rec.input(name, e.currentTarget.value);
          edited();
        }}>${rec.shown(name)}</textarea>
    `;
  } else {
    const kind = p.kind || (p.type === 'date' ? 'date' : KIND[spec.type] || 'text');
    // A percent is shown with its "%", and the record reads the number (S12.18.5).
    const pct = kind === 'percent';
    const typed = rec.typed(name);
    const shown = typed ?? (pct && rec.get(name) != null ? rec.shown(name) + '%' : rec.shown(name));
    control = html`
      <${TypedInput} kind=${kind} value=${shown} bad=${!!error} reset=${p.reset}
        min=${p.min} max=${p.max} above=${p.above} atMost=${p.atMost} negative=${p.negative}
        noun=${p.noun}
        format=${p.format}
        clear=${p.clear} fill=${p.fill} mark=${p.mark} type=${p.type === 'date'
          ? undefined
          : p.type} placeholder=${p.placeholder}
        disabled=${p.disabled} style=${p.style} readonly=${reading}
        ...${named} onInput=${(/** @type {string} */ v) => {
          rec.input(name, v, pct ? v.trim().replace(/%$/, '') : v);
          edited();
        }} />
    `;
  }
  if (p.bare) return control;
  return html`
    <${Field} label=${p.label} id=${p.id} hint=${p.hint} error=${error}
      help=${p.help}>${control}</${Field}>
  `;
}

/**
 * A record's refusals that its row's bare fields can't show (S12.15.4): each reason, on a row
 * of its own under the record's, across `span` columns.
 * @param {{ rec: import('../app/draft.js').Record, span: number }} p
 */
export function RowErrors({ rec, span }) {
  const errors = rec.errors;
  if (!errors.length) return null;
  return html`
    <tr class="row-err">
      <td colspan=${span}>
        <div class="err" role="alert">${errors.map((e) => e.message).join(
          ' ',
        )}</div>
      </td>
    </tr>
  `;
}

/**
 * One record saved at once, as a switch or a choice saves it: `existing` (its id, version and
 * fields as read) changed to `values`, or made from them when there is none.
 * @param {new (...a: any[]) => import('../app/draft.js').Record} Cls
 * @param {any} existing
 * @param {{ [name: string]: any }} values
 */
export function saveOne(Cls, existing, values) {
  return saveNow((d) => {
    if (!existing?.id) return void d.add(Cls, values);
    const r = d.load(Cls, existing);
    for (const [k, v] of Object.entries(values)) r.set(k, v);
  });
}

/**
 * A record made or deleted at once, through the save (S13.8.11): a list's own Delete, or a
 * small form of one field beside it. Anything but a save is thrown, with its reasons.
 * @param {(draft: Draft) => void} fill @returns {Promise<any[]>}  what was saved
 */
export async function saveNow(fill) {
  const draft = new Draft();
  fill(draft);
  const o = await draft.save();
  if (o.status === 'saved') return o.saved;
  const reasons = o.status === 'asks'
    ? o.asks.map((/** @type {any} */ a) => a.message)
    : o.status === 'stale'
    ? ['It changed since this page read it: reload and try again.']
    : draft.records.flatMap((r) => r.errors.map((e) => e.message)).concat(
      draft.formError ? [draft.formError] : [],
    );
  throw Object.assign(new Error(reasons.join(' ') || 'Nothing was saved.'), {
    errors: draft.records.flatMap((r) => r.errors),
  });
}
