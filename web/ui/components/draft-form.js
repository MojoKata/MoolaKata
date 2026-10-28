// The shared form pieces (requirements S12.15, S17.3.9.6): a form is its fields and nothing
// more. useDraft reads a form's records into a draft, and reads them again after a 412;
// DraftDialog and DraftForm ask before discarding changes, save, then save anyway or reload,
// and show what a save came to above the buttons; RecField draws one field of a record by its
// type.
import { useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { html } from '../app/html.js';
import { useSubmit } from '../app/hooks.js';
import { Draft } from '../app/draft.js';
import { Dialog, openDialog } from './dialog.js';
import { guardForm } from '../app/guard.js';
import { Field, FormError, Input, Select, Switch } from './fields.js';
import { Failed, Loading } from './bits.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';

/**
 * A form's draft: `load(draft)` reads its records into a new draft, on the first draw, when
 * `deps` change, and on `reload` (after a 412, S12.15.5), which drops the changes made.
 * @param {(draft: Draft) => Promise<any> | any} load
 * @param {any[]} [deps]
 * @param {{ newId?: (prefix: string) => string }} [o]
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
    const draft = new Draft(o.newId ? { newId: o.newId } : {});
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
 * @param {{ outcome: any, draft: Draft | null, what: string }} p
 */
export function SaveOutcome({ outcome, draft, what }) {
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
 * Delete removes its record and saves); `hideSave` leaves the save's button out.
 * @param {{ f: ReturnType<typeof useDraft>, title: string, close: (v?: any) => void,
 *   what: string, done?: string, label?: string, confirm?: string, wide?: boolean, note?: any,
 *   before?: () => boolean | void, changed?: () => boolean, disabled?: boolean,
 *   saved?: (o: any) => void, hideSave?: boolean,
 *   extra?: (s: { save: any, outcome: any }) => any, children: any }} p
 */
export function DraftDialog(p) {
  const { f, close } = p;
  const draft = f.draft;
  // The fields come once the records are read: the first takes the focus then (S12.1.3).
  useEffect(() => {
    if (!draft) return;
    const box = document.querySelector('.dialog .body');
    if (!box || box.contains(document.activeElement)) return;
    /** @type {HTMLElement | null} */ (box.querySelector(
      'input:not([type=hidden]):not(:disabled),select:not(:disabled),textarea:not(:disabled)',
    ))?.focus();
  }, [draft]);
  const { save, outcome, clear } = useSave(draft, {
    before: p.before,
    saved: p.saved || ((o) => {
      if (p.done) toast(p.done);
      close(o.saved);
    }),
  });
  return html`
    <${Dialog} title=${p.title} wide=${p.wide} close=${close} note=${p.note}
      changed=${p.changed || (() => !!draft?.changed)}
      onSubmit=${() => save.run().catch(() => {})}
      footer=${html`
        ${p.extra?.({ save, outcome }) || null}${p.hideSave ? null : html`
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
        : p.children}
      <${SaveOutcome} outcome=${outcome} draft=${draft} what=${p.what} />
      <${FormError} error=${save.error} />
    </${Dialog}>
  `;
}

/**
 * The question before a screen's form loses its changes (S12.15.6).
 * @param {{ close: (v?: any) => void, where: string }} p
 */
function DiscardDialog({ close, where }) {
  return html`
    <${Dialog} title="Discard your changes?" close=${() => close(false)} footer=${html`
      <button type="button" class="btn danger" onClick=${() => close(true)}>Discard</button>
      <button type="button" class="btn primary" autofocus onClick=${() =>
        close(false)}>Keep editing</button>
    `}>
      <p class="small dim">What you changed in ${where} isn't saved. Keep editing to save it, or
        discard it and go on.</p>
      </${Dialog}>
  `;
}

/**
 * A screen's form that edits a draft (Settings, Profile; S12.15): its own Save, and while it
 * holds changes, moving elsewhere in the app, Back or leaving the page asks first. `where`
 * names it in the question ("Settings › General").
 * `extra` draws the buttons beside Save, given the save (a Delete removes its record and saves);
 * `class` styles the form (a card).
 * @param {{ f: ReturnType<typeof useDraft>, where: string, what: string, done?: string,
 *   label?: string, confirm?: string, before?: () => boolean | void,
 *   saved?: (o: any) => void, extra?: (s: { save: any, outcome: any }) => any,
 *   class?: string, children: any }} p
 */
export function DraftForm(p) {
  const { f } = p;
  const draft = f.draft;
  const { route } = useLocation();
  const { save, outcome, clear } = useSave(draft, {
    before: p.before,
    saved: p.saved || (() => {
      if (p.done) toast(p.done);
      f.reload();
    }),
  });
  const changedRef = useRef(/** @type {() => boolean} */ (() => false));
  changedRef.current = () => !!draft?.changed;
  useEffect(
    () =>
      guardForm({
        has: () => changedRef.current(),
        where: p.where,
        ask: (where) => openDialog(DiscardDialog, { where }),
        route,
      }),
    [p.where],
  );
  return html`
    <form class=${p.class || 'draft-form'} onSubmit=${(/** @type {Event} */ e) => {
      e.preventDefault();
      save.run().catch(() => {});
    }}>
      ${f.error
        ? html`<${Failed} error=${f.error} />`
        : !draft
        ? html`<${Loading} lines=${4} />`
        : p.children}
      <${SaveOutcome} outcome=${outcome} draft=${draft} what=${p.what} />
      <${FormError} error=${save.error} />
      <div class="toolbar mt">
        ${p.extra?.({ save, outcome }) || null}<span class="spacer"></span>
        <${SaveButton} outcome=${outcome} busy=${save.busy} ready=${!!draft}
          label=${p.label || 'Save'} confirm=${p.confirm || 'Save anyway'} reload=${() => {
            clear();
            f.reload();
          }} />
      </div>
    </form>
  `;
}

/** What a field's input reads, by type. */
const TYPED = new Set(['money', 'quantity', 'percent', 'int']);

/**
 * One field of a record, drawn by its type (S17.3.9.6): text for money and quantities, a list
 * for a choice or a reference (`options`, as [value, label]), a switch for yes or no; bound to
 * the record: its value, what was typed, its refusal; hidden while a rule says it doesn't
 * apply. `bare` draws the control alone (a table's cell), named by `label` and `help`.
 * `id` names the control where its label alone wouldn't (`f-` and the id, S12.7.3).
 * @param {{ rec: import('../app/draft.js').Record, name: string, label: string, id?: string,
 *   'data-help'?: string, 'aria-invalid'?: string, 'aria-describedby'?: string,
 *   options?: ([string, string] | string)[], hint?: any, help?: string, bare?: boolean,
 *   type?: string, placeholder?: string, disabled?: boolean, onEdit?: () => void,
 *   style?: any, rows?: number }} p
 */
export function RecField(p) {
  const { rec, name } = p;
  if (!rec.applies(name)) return null;
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
        disabled=${p.disabled} aria-invalid=${error ? 'true' : undefined} ...${named}
        onChange=${(/** @type {string} */ v) => {
          rec.input(name, v);
          edited();
        }} />
    `;
  } else if (p.rows) {
    control = html`
      <textarea class="in" rows=${p.rows} disabled=${p.disabled} ...${named}
        onInput=${(/** @type {any} */ e) => {
          rec.input(name, e.currentTarget.value);
          edited();
        }}>${rec.shown(name)}</textarea>
    `;
  } else {
    control = html`
      <${Input} value=${rec.shown(name)} bad=${!!error}
        type=${p.type || (spec.type === 'date' ? 'date' : 'text')} placeholder=${p.placeholder}
        inputmode=${TYPED.has(spec.type) ? 'decimal' : undefined} disabled=${p.disabled}
        style=${p.style} ...${named} onInput=${(/** @type {string} */ v) => {
          rec.input(name, v);
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
