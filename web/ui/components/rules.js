// Categorisation and payee rules (requirements S2.7): Transactions › Rules (S12.2.3.2) lists a
// user's own rules on the left, first match wins, and shows the one chosen on the right, each at
// its own address; Make a rule opens New rule over a transaction's dialog (S2.7.6). Applied on
// import and on demand.
import { effect, signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { money } from '../app/format.js';
import { confirmAction } from './confirm.js';
import { useDialogGuide, useGuide } from './help.js';
import { FormError } from './fields.js';
import { Record } from '../app/draft.js';
import { DraftDialog, DraftForm, RecField, saveNow, saveOne, useDraft } from './draft-form.js';
import { FIELDS } from '../api/fields.js';
import { Failed, Loading } from './bits.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';
import { TagsField } from './tags.js';
import { CategoryField } from './categories.js';

const DIRECTIONS = [['any', 'Money in or out'], ['out', 'Money out'], ['in', 'Money in']];
const RULES = '/ui/transactions/rules';

/** @param {any} r */
function when(r) {
  const parts = [r.payeeMatch.toLowerCase().startsWith('re:') ? r.payeeMatch : `“${r.payeeMatch}”`];
  if (r.amountMin != null || r.amountMax != null) {
    parts.push(
      r.amountMin != null && r.amountMax != null
        ? `${money(r.amountMin)}–${money(r.amountMax)}`
        : r.amountMin != null
        ? `${money(r.amountMin)} or more`
        : `up to ${money(r.amountMax)}`,
    );
  }
  if (r.direction !== 'any') parts.push(r.direction === 'in' ? 'money in' : 'money out');
  if (r.accountId) parts.push(`in ${r.accountName}${r.accountDeleted ? ' (deleted)' : ''}`);
  return parts.join(' · ');
}

/** @param {any} r */
function sets(r) {
  const parts = [];
  if (r.categoryId) parts.push(`${r.categoryPath}${r.categoryDeleted ? ' (deleted)' : ''}`);
  if (r.payee) parts.push(`shown as ${r.payee}`);
  if (r.tags.length) parts.push(r.tags.map((/** @type {string} */ t) => `#${t}`).join(' '));
  return parts.join(' · ');
}

/** A rule (S2.7), as its form's draft edits it. */
export class RuleRec extends Record {
  /** @override */
  static prefix = 'Rule';
  /** @override */
  static fields = FIELDS.RuleRecord;
  /** @override */
  static defaults = { direction: 'any', tagIds: [] };
}

/**
 * A rule's fields: the Rules tab's right side, and New rule over a transaction's dialog.
 * @param {{ rec: RuleRec, draft: import('../app/draft.js').Draft }} p
 */
function RuleFields({ rec, draft }) {
  const accounts = useList('/accounts');
  const writable = (/** @type {any[]} */ (accounts.data) || []).filter((a) => a.access.writable);
  return html`
    <${RecField} rec=${rec} name="payeeMatch" label="Payee contains"
      placeholder="WHOLE FOODS, or re:^AMZN"
      hint="As the bank writes it; case doesn't matter. re: starts a regular expression." />
    <div class="row">
      <${RecField} rec=${rec} name="amountMin" label="Amount from" placeholder="any" />
      <${RecField} rec=${rec} name="amountMax" label="Amount to" placeholder="any" />
    </div>
    <div class="row">
      <${RecField} rec=${rec} name="direction" label="Direction" options=${DIRECTIONS} />
      <${RecField} rec=${rec} name="accountId" label="Account" options=${[
        ['', 'Any account'],
        ...writable.map((a) => [a.id, a.name]),
      ]} />
    </div>
    <${CategoryField} rec=${rec} name="categoryId" label="Category"
      first=${['', 'Leave it as it is']} />
    <${RecField} rec=${rec} name="payee" label="Rename to" placeholder="leave the payee"
      hint="The payee shown; the bank's text is kept beside it." />
    <${TagsField} rec=${rec} draft=${draft} placeholder="coffee, work"
      hint="Your own, separated by commas." />
  `;
}

/**
 * New rule, over the transaction's dialog that made it (S2.7.6, S12.15.7): filled from the
 * transaction, saved with its own Save; the transaction's dialog stays as it was.
 * @param {{ close: (v?: any) => void, fill: { payeeMatch: string, categoryId: string | null } }} p
 */
export function NewRuleDialog({ close, fill }) {
  useDialogGuide('dialog-rule');
  const f = useDraft((draft) => {
    draft.add(RuleRec, { payeeMatch: fill.payeeMatch, categoryId: fill.categoryId });
  });
  const rec = /** @type {RuleRec | undefined} */ (f.draft?.records[0]);
  return html`
    <${DraftDialog} f=${f} title="New rule" close=${close} what="This rule"
      label="Add the rule" done="Rule added"
      extra=${() => html`<button type="button" class="btn" data-cancel>Cancel</button>`}>
      ${rec && f.draft ? html`<${RuleFields} rec=${rec} draft=${f.draft} />` : null}
    </${DraftDialog}>
  `;
}

/** Whether the rule shown on the Rules tab holds changes: what acts on the saved rules waits. */
const ruleChanged = signal(false);

/**
 * A button that acts on the saved rules: while the rule shown has changes, it is off, and says
 * why (S12.2.3.2.4).
 * @param {{ children: any }} p
 */
function SavedFirst({ children }) {
  return ruleChanged.value
    ? html`<span class="tip-wrap" data-tip="Save changes first">${children}</span>`
    : children;
}

/**
 * Transactions › Rules (S12.2.3.2): the rules on the left, the one chosen on the right.
 * `id` is the rule chosen, `new` for one being added, or nothing.
 * @param {{ id?: string }} p
 */
export function RulesTab({ id }) {
  useGuide('transactions-rules');
  const res = useApi('/rules');
  const v = /** @type {any} */ (res.data);
  const rows = v ? /** @type {any[]} */ (v.items) : null;
  const fresh = id === 'new';
  const rule = rows && id && !fresh ? rows.find((r) => r.id === id) || null : null;
  const changed = ruleChanged.value;
  const act = useSubmit(async (/** @type {() => Promise<any>} */ f) => {
    await f();
    res.reload();
  });
  const apply = useSubmit(async () => {
    const r = await api.post('/rules/apply', {});
    toast(r.changed === 1 ? 'Set 1 transaction' : `Set ${r.changed} transactions`);
    res.reload();
  });
  // Up or down the list: its position, the others closing up around it (S2.7).
  const move = (/** @type {any} */ r, /** @type {number} */ to) =>
    act.run(() => saveOne(RuleRec, r, { position: to })).catch((e) => toast(e.message));
  const arrow = (/** @type {any} */ r, /** @type {number} */ i, /** @type {number} */ to) => {
    const up = to < i;
    return html`<${SavedFirst}><button type="button" class="btn sm"
      aria-label=${`Move rule ${i + 1} ${up ? 'up' : 'down'}`}
      disabled=${(up ? i === 0 : i === (rows?.length ?? 0) - 1) || changed || act.busy}
      onClick=${() => move(r, to)}>${up ? '↑' : '↓'}</button></${SavedFirst}>`;
  };
  return html`
    <div class="rules-layout">
      <div class="card">
        <div class="toolbar">
          <a class="btn" href=${RULES + '/new'}><${Icon} name="plus" /> Add rule</a>
          ${v?.uncategorised
            ? html`<${SavedFirst}><button type="button" class="btn"
              disabled=${changed || apply.busy} onClick=${() => apply.run().catch(() => {})}>
              Apply to ${v.uncategorised} uncategorised</button></${SavedFirst}>`
            : null}
        </div>
        <p class="small dim" data-help="first-match">First match wins, top to bottom. Applied to
          what you import, and to the uncategorised when you choose.</p>
        ${res.error
          ? html`<${Failed} error=${res.error} />`
          : !rows
          ? html`<${Loading} lines=${3} />`
          : html`
            ${rows.map((r, i) =>
              html`
                <div class=${'list-item rule-row' + (r.id === id ? ' sel' : '')} key=${r.id}>
                  <span class="dim small rule-n">${i + 1}</span>
                  <a class="grow rule-link" href=${RULES + '/' + r.id}
                    aria-current=${r.id === id ? 'true' : undefined}>${when(r)}<div
                      class="small">${sets(r)}</div></a>
                  <span class="rule-moves">${arrow(r, i, i - 1)} ${arrow(r, i, i + 1)}</span>
                </div>
              `
            )}
            ${fresh
              ? html`
                <div class="list-item rule-row sel">
                  <span class="dim small rule-n">${rows.length + 1}</span>
                  <span class="grow"><i>New rule</i></span>
                  <span class="pill new">not saved</span>
                </div>
              `
              : null}
            ${!rows.length && !fresh
              ? html`<p class="small dim">No rules yet. <b>Add rule</b>, or <b>Make a rule</b>
                from a transaction.</p>`
              : null}
          `}
        <${FormError} error=${act.error || apply.error} />
      </div>
      ${!rows || (id && !fresh && !rule && res.loading)
        ? html`
          <div class="card">
            <${Loading} lines=${6} />
          </div>
        `
        : fresh || rule
        ? html`
          <${RulePane} key=${id} rule=${rule} n=${rule ? rows.indexOf(rule) + 1 : 0}
            listed=${res.reload} />
        `
        : html`
          <div class="card">
            <p class="dim" style=${{ margin: 0 }}>${id
              ? 'This rule is gone: deleted, here or elsewhere.'
              : 'Choose a rule to see and change it, or Add rule.'}</p>
          </div>
        `}
    </div>
  `;
}

/**
 * The rule chosen, or one being added (`rule` null): its fields edit a draft; Discard and Save
 * show while it holds changes, and leaving it asks first (S12.2.3.2).
 * @param {{ rule: any | null, n: number, listed: () => void }} p
 */
function RulePane({ rule, n, listed }) {
  const { route } = useLocation();
  const f = useDraft((draft) => {
    if (rule) draft.load(RuleRec, rule);
    else draft.add(RuleRec, { payeeMatch: '', categoryId: null });
  }, [rule?.id ?? 'new']);
  const rec = /** @type {RuleRec | undefined} */ (f.draft?.records[0]);
  // A rule being added is a change from the start: Add rule put it in the list.
  const has = () => !rule || !!f.draft?.changed;
  // Read through the records' signals once the draft is there, so it follows each edit
  // (S12.2.3.2.4).
  useEffect(() => {
    const draft = f.draft;
    const stop = effect(() => void (ruleChanged.value = !rule || !!draft?.changed));
    return () => {
      stop();
      ruleChanged.value = false;
    };
  }, [f.draft]);
  return html`
    <${DraftForm} f=${f} class="card rule-pane" where="this rule" what="This rule"
      changed=${has}
      discard=${() => (rule ? f.draft?.revertAll() : route(RULES))}
      saved=${(/** @type {any} */ o) => {
        toast(rule ? 'Rule saved' : 'Rule added');
        listed();
        const made = o.saved?.find((/** @type {any} */ x) => x.entity === 'Rule')?.record;
        if (!rule && made) route(RULES + '/' + made.id, true);
        else f.reload();
      }}
      extra=${() =>
        rule
          ? html`<button type="button" class="btn danger" onClick=${async () => {
            if (!(await confirmAction({ title: 'Delete this rule?' }))) return;
            try {
              await saveNow((d) => d.remove(d.load(RuleRec, rule)));
            } catch (e) {
              return toast(/** @type {any} */ (e).message);
            }
            toast('Rule deleted');
            listed();
            route(RULES, true);
          }}>Delete</button>`
          : null}>
      <h3>${rule ? `Rule ${n}` : 'New rule'}</h3>
      ${rec && f.draft ? html`<${RuleFields} rec=${rec} draft=${f.draft} />` : null}
    </${DraftForm}>
  `;
}
