// Categorisation and payee rules (requirements S2.7): Transactions › Rules lists a user's own
// rules, first match wins, and edits them one at a time; applied on import and on demand.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { money } from '../app/format.js';
import { Dialog, openDialog } from './dialog.js';
import { useDialogGuide } from './help.js';
import { FormError } from './fields.js';
import { Record } from '../app/draft.js';
import { DraftDialog, RecField, saveNow, useDraft } from './draft-form.js';
import { FIELDS } from '../api/fields.js';
import { Failed, Loading } from './bits.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';

const DIRECTIONS = [['any', 'Money in or out'], ['out', 'Money out'], ['in', 'Money in']];

/**
 * The list, and the editor in turn: one dialog at a time, so editing closes the list and
 * opens it again after.
 * @param {any} [start]  a rule to make first, filled from a transaction
 */
export async function openRules(start) {
  let edit = start ? { rule: null, fill: start } : null;
  for (;;) {
    if (edit) {
      await openDialog(RuleDialog, edit);
      edit = null;
    }
    const next = await openDialog(RulesDialog, {});
    if (!next) return;
    edit = next;
  }
}

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

/** @param {{ close: (v?: any) => void }} p */
function RulesDialog({ close }) {
  useDialogGuide('dialog-rules');
  const res = useApi('/rules');
  const v = /** @type {any} */ (res.data);
  const [armed, setArmed] = useState(/** @type {string | null} */ (null));
  const act = useSubmit(async (/** @type {() => Promise<any>} */ f) => {
    await f();
    setArmed(null);
    res.reload();
  });
  const apply = useSubmit(async () => {
    const r = await api.post('/rules/apply', {});
    toast(r.changed === 1 ? 'Set 1 transaction' : `Set ${r.changed} transactions`);
    close();
  });
  const move = (/** @type {any} */ r, /** @type {number} */ to) =>
    act.run(() => api.post(`/rules/${r.id}/move`, { to })).catch(() => {});
  const rows = v ? /** @type {any[]} */ (v.items) : null;
  return html`
    <${Dialog} title="Categorisation rules" wide close=${close}
      onSubmit=${() => apply.run().catch(() => {})}
      footer=${html`
        <button type="button" class="btn" onClick=${() => close({ rule: null })}><${Icon}
          name="plus" /> Add a rule</button>
        <span class="spacer" style=${{ flex: 1 }}></span>
        <button type="button" class="btn" onClick=${() => close()}>Close</button>
        <button class="btn primary" disabled=${!v?.uncategorised || apply.busy}>${v?.uncategorised
          ? `Apply to ${v.uncategorised} uncategorised`
          : 'Nothing uncategorised to set'}</button>
      `}>
      <p class="small dim" style=${{ marginTop: 0 }} data-help="first-match">First match wins, top
        to bottom. Applied to what you import, and to the uncategorised when you choose.</p>
      ${res.error
        ? html`<${Failed} error=${res.error} />`
        : !rows
        ? html`<${Loading} lines=${3} />`
        : !rows.length
        ? html`<p class="small dim">No rules yet. <b>Add a rule</b>, or <b>Make a rule</b> from a
          transaction.</p>`
        : html`
          <div class="table-wrap">
            <table class="t">
              <thead>
                <tr>
                  <th>#</th>
                  <th>When</th>
                  <th
                  >Then</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>${rows.map((r, i) =>
                html`
                  <tr>
                    <td class="dim">${i + 1}</td>
                    <td>${when(r)}</td>
                    <td>${sets(r)}</td>
                    <td
                      style=${{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                      <button type="button" class="btn sm" aria-label=${`Move rule ${i + 1} up`}
                        disabled=${i === 0 || act.busy} onClick=${() => move(r, i - 1)}>↑</button>
                      <button type="button" class="btn sm" aria-label=${`Move rule ${i + 1} down`}
                        disabled=${i === rows.length - 1 || act.busy} onClick=${() =>
                          move(r, i + 1)}>↓</button>
                      <button type="button" class="btn sm" onClick=${() =>
                        close({ rule: r })}>Edit…</button>
                      <button type="button" class="btn sm danger" disabled=${act.busy}
                        onClick=${() =>
                          armed === r.id
                            ? act.run(() => saveNow((d) => d.remove(d.load(RuleRec, r))))
                              .catch(() => {})
                            : setArmed(r.id)}>${armed === r.id
                          ? 'Click again to delete'
                          : 'Delete'}</button>
                    </td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        `}
      <${FormError} error=${act.error || apply.error} />
    </${Dialog}>
  `;
}

/** A rule (S2.7), as its dialog's draft edits it. */
class RuleRec extends Record {
  /** @override */
  static prefix = 'Rule';
  /** @override */
  static fields = FIELDS.RuleRecord;
  /** @override */
  static defaults = { direction: 'any', tags: [] };
}

/** @param {{ close: (v?: any) => void, rule: any, fill?: any }} p */
function RuleDialog({ close, rule, fill }) {
  useDialogGuide('dialog-rule');
  const accounts = useList('/accounts');
  const cats = useList('/categories');
  const f = useDraft((draft) => {
    if (rule) draft.load(RuleRec, rule);
    else {
      draft.add(RuleRec, {
        payeeMatch: fill?.payeeMatch ?? '',
        categoryId: fill?.categoryId || null,
      });
    }
  }, [rule?.id]);
  const rec = /** @type {RuleRec | undefined} */ (f.draft?.records[0]);
  const writable = (/** @type {any[]} */ (accounts.data) || []).filter((a) => a.level !== 'read');
  return html`
    <${DraftDialog} f=${f} title=${rule ? 'Edit a rule' : 'New rule'} close=${close}
      what="This rule" label=${rule ? 'Save' : 'Add the rule'}
      done=${rule ? 'Rule saved' : 'Rule added'}
      extra=${() => html`<button type="button" class="btn" data-cancel>Cancel</button>`}>
      ${rec
        ? html`
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
          <${RecField} rec=${rec} name="categoryId" label="Category" options=${[
            ['', 'Leave it as it is'],
            ...(/** @type {any[]} */ (cats.data) || []).map((c) => [c.id, c.path]),
          ]} />
          <${RecField} rec=${rec} name="payee" label="Rename to" placeholder="leave the payee"
            hint="The payee shown; the bank's text is kept beside it." />
          <${RecField} rec=${rec} name="tags" label="Tags" placeholder="coffee, work"
            hint="Your own, separated by commas." />
        `
        : null}
    </${DraftDialog}>
  `;
}
