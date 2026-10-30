// New account (requirements S12.2.2): a type picker, then the account form.
import { useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { html } from '../app/html.js';
import { Dialog } from '../components/dialog.js';
import { useDialogGuide } from '../components/help.js';
import { Field, Select } from '../components/fields.js';
import { Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { DraftDialog, RecField, useDraft } from '../components/draft-form.js';
import { Tile } from '../components/bits.js';
import { toast } from '../components/toast.js';
import { BY_TYPE, TYPES } from '../account-types/index.js';
import { LoanRec, newTerms, TermsFields } from '../components/loan.js';
import { EduPlanRec, PlanFields } from '../components/edu.js';
import { WalletFields } from '../components/wallet.js';

export const LOT_METHODS = /** @type {[string, string][]} */ ([
  ['fifo', 'FIFO (first in, first out)'],
  ['lifo', 'LIFO (last in, first out)'],
  ['hifo', 'HIFO (highest cost first)'],
  ['specific', 'Specific identification'],
  ['average', 'Average cost'],
]);
// Imports are files and statements alike (S1.3): the choice sets only whether statements are
// expected; whether positions are holdings is told by the account's trades.
export const KEPT_BY = /** @type {[string, string][]} */ ([
  ['file', 'Imports (files and statements)'],
  ['manual', 'Manual'],
]);

/** @param {{ close: (v?: any) => void }} p */
export function NewAccount({ close }) {
  const [type, setType] = useState(/** @type {string | null} */ (null));
  useDialogGuide(type ? 'dialog-account-form' : 'dialog-new-account');
  if (!type) {
    return html`
      <${Dialog} title="New account" wide close=${close} footer=${null}>
        <p class="small dim" style=${{
          marginTop: 0,
        }}>Choose the type. It decides the fields, the tax
              treatment and how the account can be kept current.</p>
        <div class="type-grid">${TYPES.map((t) =>
          html`<button type="button" class="type-card" onClick=${() => setType(t.type)}>
          <${Tile} group=${t.group} icon=${t.icon} /><div style=${{
            textAlign: 'left',
          }}><div>${t.label}</div>
          <div class="sub">${t.hint}</div></div></button>`
        )}</div>
        </${Dialog}>
    `;
  }
  return html`<${AccountForm} type=${type} close=${close} back=${() => setType(null)} />`;
}

/** An account (S1), as New account's draft and its Settings edit it. */
export class AcctRec extends Record {
  /** @override */
  static prefix = 'Acct';
  /** @override */
  static fields = FIELDS.AccountRecord;
  /** @override */
  static defaults = {
    institution: null,
    mask: null,
    notes: null,
    keptBy: ['file'],
    lotMethod: 'fifo',
    openingBalance: null,
    openingDate: null,
    countInNetWorth: null,
    active: true,
    statementInterval: null,
    withdrawalsAMonth: null,
    connectionId: null,
    syncAccount: null,
    walletKeys: null,
    gapLimit: 20,
  };
}

/** @param {{ type: string, close: (v?: any) => void, back: () => void }} p */
function AccountForm({ type, close, back }) {
  const { route } = useLocation();
  const t = BY_TYPE[type];
  const d = useDraft((draft) => {
    const kept = t.loan || t.physical ? ['manual'] : t.wallet ? ['bitcoin'] : ['file'];
    const a = draft.add(AcctRec, { name: '', type, keptBy: kept });
    if (t.loan) draft.add(LoanRec, newTerms(type, a.id));
    if (t.education) draft.add(EduPlanRec, { accountId: a.id }, { optional: true });
  }, [type]);
  const draft = d.draft;
  const acct = /** @type {AcctRec | undefined} */ (draft?.records[0]);
  const loan = /** @type {LoanRec | undefined} */ (
    draft?.records.find((r) => r instanceof LoanRec)
  );
  const plan = /** @type {EduPlanRec | undefined} */ (
    draft?.records.find((r) => r instanceof EduPlanRec)
  );
  /** The account made, with its terms, plan or keys: then its page. */
  const made = (/** @type {any} */ o) => {
    const a = o.saved.find((/** @type {any} */ x) => x.entity === 'Acct').record;
    toast(`${a.name} made`);
    close(a);
    route(`/ui/accounts/${a.id}`);
  };
  return html`
    <${DraftDialog} f=${d} title=${`New ${t.label} account`} close=${close} what="This account"
      label="Create" saved=${made}
      extra=${() => html`<button type="button" class="btn" onClick=${back}>Back</button>`}>
      ${acct
        ? html`
          <${RecField} rec=${acct} name="name" label="Name" placeholder=${t.investing
            ? 'Individual brokerage'
            : t.loan
            ? t.label
            : 'Everyday checking'} />
          <div class="row">
            <${RecField} rec=${acct} name="institution" label="Institution"
              placeholder="The bank or broker" />
            <${RecField} rec=${acct} name="mask" label="Last 4" id="mask"
              placeholder="4821" />
          </div>
          ${t.education && plan && draft
            ? html`<${PlanFields} rec=${plan} draft=${draft} />`
            : null}
          ${t.wallet
            ? html`
              <p class="small dim">Bitcoin. Other coins come later.</p>
              <${WalletFields} rec=${acct} />
              <${RecField} rec=${acct} name="lotMethod" label="Lot method" options=${LOT_METHODS}
                hint="How sales pick lots. The method in force at a sale is recorded with it." />
            `
            : t.loan && loan
            ? html`<${TermsFields} rec=${loan} type=${type} />`
            : t.physical
            ? html`<p class="small dim">Add the items after making the account, each with its
              purchase date, cost basis, notes and documents.</p>`
            : html`
              <${KeptBy} rec=${acct} />
              ${t.investing
                ? html`
                  <${RecField} rec=${acct} name="lotMethod" label="Lot method"
                    options=${LOT_METHODS}
                    hint="How sales pick lots. The method in force at a sale is recorded with it." />
                `
                : null}
              <div class="row">
                <${RecField} rec=${acct} name="openingBalance" label="Opening balance"
                  placeholder="0.00"
                  hint="Optional. Without it, the first imported balance stands in." />
                <${RecField} rec=${acct} name="openingDate" label="Opening balance date"
                  id="opening-date" type="date" />
              </div>
            `}
        `
        : null}
    </${DraftDialog}>
  `;
}

/**
 * How the account is kept current: one way, of the list the account's record keeps.
 * @param {{ rec: AcctRec, label?: string }} p
 */
export function KeptBy({ rec, label = 'Keep it current by' }) {
  return html`
    <${Field} label=${label} id="kept-by" error=${rec.error('keptBy')}>
      <${Select} value=${(rec.get('keptBy') || [])[0] || 'manual'} onChange=${(
        /** @type {string} */ v,
      ) => rec.set('keptBy', [v])} options=${KEPT_BY} />
      </${Field}>
  `;
}
