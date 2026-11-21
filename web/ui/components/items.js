// A physical-asset account's items (requirements S1.10): the Items tab, with precious metals
// summarised by metal; the item dialog, with its fields, valuations, a property's
// improvements, photos and documents, the loans it secures, and its sale.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList } from '../app/hooks.js';
import { date, quantity } from '../kit/format.js';
import { useFormats } from '../kit/formats.js';
import { Amt } from '../kit/amount.js';
import { Empty, Failed, Loading, Tabs } from '../kit/bits.js';
import { TimeChart } from '../charts/chart.js';
import { openDialog } from '../kit/dialog.js';
import { useDialogGuide } from './help.js';
import { Field, Input, Select, TypedInput } from '../kit/fields.js';
import { Reads } from './reads.js';
import { Icon } from '../kit/icon.js';
import { toast } from '../kit/toast.js';
import { ACCEPT, uploadAll } from './receipt.js';
import { BY_TYPE } from '../account-types/index.js';
import { Dec, dec, num } from '../kit/dec.js';
import { READ_ONLY, Record, whyNotAdd, whyRead } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { DraftDialog, RecField, useDraft } from './draft-form.js';
import { Action, Attention, RowTool, StatePill } from '../kit/state.js';

export const METALS = /** @type {[string, string][]} */ ([
  ['gold', 'Gold'],
  ['silver', 'Silver'],
  ['platinum', 'Platinum'],
  ['palladium', 'Palladium'],
]);
const FORMS = ['Coin', 'Bar', 'Round', 'Jewellery'];
const UNITS = /** @type {[string, string][]} */ ([
  ['ozt', 'troy oz'],
  ['g', 'grams'],
  ['kg', 'kilograms'],
]);
const CATEGORIES = [
  'Watch',
  'Coin (numismatic)',
  'Art',
  'Wine and spirits',
  'Trading cards',
  'Stamps',
  'Jewellery',
  'Other',
];
const HOW = /** @type {[string, string][]} */ ([
  ['bought', 'Bought'],
  ['gift', 'A gift (carried-over basis)'],
  ['inherited', 'Inherited (value at death)'],
]);
export const VALUED_BY = /** @type {[string, string][]} */ ([
  ['spot', 'Spot price × fine weight'],
  ['valuations', 'Valuations'],
  ['depreciation', 'Depreciation'],
]);
const SOURCES = /** @type {[string, string][]} */ ([
  ['appraisal', 'Appraisal'],
  ['sale', 'Recent sale'],
  ['guide', 'Price guide'],
  ['estimate', 'Estimate'],
]);
const SOURCE = Object.fromEntries(SOURCES);
const METAL = Object.fromEntries(METALS);
const clean = (/** @type {string} */ s) => (s ? String(s).replace(/[$,%\s]/g, '') : '');

/** @param {{ a: any }} p */
export function Items({ a }) {
  const res = useApi(`/accounts/${a.id}/items`, {}, ['prices']);
  const v = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} />`;
  const open = (/** @type {any} */ id) =>
    openDialog(ItemDialog, { a, id }).then(() => res.reload());
  const metals = a.type === 'precious-metals';
  return html`
    ${v.metals.length
      ? html`<div class="grid g2">${
        v.metals.map((/** @type {any} */ m) =>
          html`
            <div class="card">
              <h3>${METAL[m.metal]}<span class="spacer"></span><span
                      class="small dim" style=${{ fontWeight: 400 }}>${m.spot
                        ? html`spot <${Amt} v=${m.spot} />/oz · ${date(m.spotAsOf)}`
                        : 'no spot price yet'}</span></h3>
              <div class="kv">
                <div>
                  <div class="k">Fine ounces</div>
                  <div class="v">${quantity(m.ounces)}</div>
                </div>
                <div>
                  <div class="k">Average cost</div>
                  <div class="v">${m.averageCost ? html`<${Amt} v=${m.averageCost} />` : '—'}</div>
                </div>
                <div>
                  <div class="k">Value</div>
                  <div class="v">
                    <${Amt} v=${m.value} cents=${false} />
                  </div>
                </div>
                <div>
                  <div class="k">Gain</div>
                  <div class="v">
                    <${Amt} v=${m.gain} signed
                      cents=${false} />
                  </div>
                </div>
              </div>
            </div>
          `
        )
      }</div>`
      : null}
    <div class=${'card' + (v.metals.length ? ' mt' : '')} style=${{ padding: '4px 8px' }}>
      <h3 style=${{ padding: '8px 8px 0' }}>Items<span class="spacer"></span><${Action}
        class="btn sm" why=${whyNotAdd('Item', a)} onClick=${() => open(null)}><${Icon}
        name="plus" /> Add an Item</${Action}></h3>
      ${v.items.length
        ? html`
          <div class="table-wrap">
            <table class="t">
              <caption class="sr-only">Items</caption>
              <thead>
                <tr><th>Item</th>${metals
                  ? html`<th class="num">Fine oz</th>`
                  : null}<th>Acquired</th><th class="num">Cost Basis</th><th>Value</th>
                      <th class="num">Gain</th><th></th></tr>
              </thead>
              <tbody>${v.items.map((/** @type {any} */ i) =>
                html`<tr>
              <td>${i.name}<div class="small dim">${
                  [
                    i.metal ? METAL[i.metal] : null,
                    i.category,
                    !dec(i.quantity).eq(1) ? `× ${quantity(i.quantity)}` : null,
                  ].filter(Boolean).join(' · ')
                }</div></td>
              ${
                  metals
                    ? html`<td class="num">${i.fineOunces ? quantity(i.fineOunces) : '—'}</td>`
                    : null
                }
              <td class="small dim" style=${{ whiteSpace: 'nowrap' }}>${
                  date(i.acquiredOn)
                }<div>${i.years} yr</div></td>
              <td class="num"><${Amt} v=${i.basis} cents=${false} /></td>
              <td>${
                  i.sale
                    ? html`<span class="pill">sold ${date(i.sale.soldOn)}</span>`
                    : html`<b><${Amt} v=${i.value} cents=${false} /></b>${
                      i.latest
                        ? html`<div class="small dim">${SOURCE[i.latest.source]} · ${
                          date(
                            i.latest
                              .date,
                          )
                        } ${
                          i.stale
                            ? html`<${StatePill} tone="warn" why=${STALE}>stale</${StatePill}>`
                            : null
                        }</div>`
                        : html`<div class="small dim">${
                          VALUED_BY.find(([k]) => k === i.valuation)?.[1]
                        }</div>`
                    }${
                      i
                          .equity != null
                        ? html`<div class="small dim">equity <${Amt} v=${i.equity} cents=${false} /></div>`
                        : null
                    }`
                }</td>
              <td class="num"><${Amt} v=${i.gain} signed cents=${false} /></td>
              <td class="tool"><${RowTool} name=${i.name} read=${!a.access.writable}
                onClick=${() => open(i.id)} /></td></tr>`
              )}</tbody>
              <tfoot>
                <tr>
                  <td colspan=${metals ? 3 : 2}><b>Held now</b></td>
                  <td class="num">
                    <${Amt}
                      v=${v.basis} cents=${false} />
                  </td>
                  <td><b><${Amt} v=${v.value} cents=${false} /></b></td>
                  <td class="num">
                    <${Amt} v=${v.gain} signed cents=${false} />
                  </td>
                  <td></td>
                </tr>
              </tfoot>
            </table>
          </div>
        `
        : html`<${Empty}>No items yet</${Empty}>`}
    </div>
  `;
}

// What the pills on an item's row and its sale mean (S12.19.3).
const STALE = 'Its latest valuation is over a year old: a newer one keeps its value true.';
const STALE_SOME = 'Valued over a year ago: newer valuations keep their value true.';
const COLLECTABLE = 'Taxed as a collectable, flagged on Form 8949.';
const PERSONAL = "A loss on property you used yourself isn't deductible.";

/** The summary on a physical-asset account's Overview. */
/** @param {{ a: any }} p */
export function ItemsSummary({ a }) {
  const res = useApi(`/accounts/${a.id}/items`, {}, ['prices']);
  const v = /** @type {any} */ (res.data);
  if (!v) {
    return html`
      <div class="card">
        <${Loading} lines=${4} />
      </div>
    `;
  }
  const held = v.items.filter((/** @type {any} */ i) => !i.sale);
  const stale = held.filter((/** @type {any} */ i) => i.stale).length;
  return html`
    <div class="card facts">
      <h3>Details</h3>
      <div class="list-item"><span class="grow dim">Type</span>${a.typeLabel}</div>
      <div class="list-item"><span class="grow dim">Items held</span>${held.length}${stale
        ? html`<${StatePill} tone="warn" why=${STALE_SOME}>${stale} stale</${StatePill}>`
        : null}</div>
      <div class="list-item"><span class="grow dim">Valued by</span>${VALUED_BY.find(([k]) =>
        k === BY_TYPE[a.type]?.physical
      )?.[1]}</div>
      <div class="list-item"><span class="grow dim">Cost basis</span><${Amt} v=${v.basis}
        cents=${false} /></div>
      <div class="list-item"><span class="grow dim">Gain</span><${Amt} v=${v.gain} signed
        cents=${false} /></div>
      <div class="list-item"><span class="grow dim">Owner</span>${a.ownerName}</div>
    </div>
  `;
}

/** An item (S1.10), as its dialog's draft edits it, its sale and documents with it. */
class ItemRec extends Record {
  /** @override */
  static prefix = 'Item';
  /** @override */
  static fields = FIELDS.ItemRecord;
  /** @override */
  static defaults = {
    category: null,
    description: null,
    acquiredHow: 'bought',
    heldFrom: null,
    quantity: Dec.parse('1'),
    location: null,
    serial: null,
    condition: null,
    insuredValue: null,
    policy: null,
    notes: null,
    metal: null,
    unitWeight: null,
    weightUnit: null,
    purity: null,
    sellPremium: Dec.parse('0'),
    depreciationRate: null,
    address: null,
    closingCosts: null,
    personalUse: false,
    soldOn: null,
    proceeds: null,
    saleFees: null,
    receiptIds: [],
  };
  /** @override */
  static rules = {
    // The giver's holding counts only for a gift (S1.10.1).
    heldFrom: { when: (/** @type {ItemRec} */ r) => r.get('acquiredHow') === 'gift' },
  };
}

/** A dated value of an item, with its source (S1.10.2). */
class ValuationRec extends Record {
  /** @override */
  static prefix = 'Valtn';
  /** @override */
  static fields = FIELDS.ValuationRecord;
  /** @override */
  static ownedBy = ['itemId'];
}

/** A residence period: one person's span of a home as their main home (S1.10.4). */
class PeriodRec extends Record {
  /** @override */
  static prefix = 'RsPrd';
  /** @override */
  static fields = FIELDS.PeriodRecord;
  /** @override */
  static ownedBy = ['itemId'];
}

/** An improvement to a property, added to its basis (S1.10.4). */
class ImprovementRec extends Record {
  /** @override */
  static prefix = 'Imprv';
  /** @override */
  static fields = FIELDS.ImprovementRecord;
  /** @override */
  static ownedBy = ['itemId'];
}

/**
 * A new item of this account type, as its type usually has it.
 * @param {string} type @param {string} accountId
 */
function newItem(type, accountId) {
  const metals = type === 'precious-metals';
  return {
    accountId,
    name: '',
    category: metals ? 'Coin' : type === 'collectables' ? 'Watch' : null,
    valuation: BY_TYPE[type]?.physical || 'valuations',
    metal: metals ? 'gold' : null,
    unitWeight: metals ? Dec.parse('1') : null,
    weightUnit: metals ? 'ozt' : null,
    purity: metals ? '.9999' : null,
    depreciationRate: type === 'vehicle' ? Dec.parse('12') : null,
    personalUse: ['vehicle', 'real-estate'].includes(type),
  };
}

/** The item dialog's tabs (S1.10.6). */
const ITEM_TABS = /** @type {[string, string][]} */ ([
  ['general', 'General'],
  ['valuation', 'Valuation'],
  ['notes', 'Notes'],
]);
const ADD_FIRST = 'Its value, valuations and sale follow once it is added.';

/** The item's fields on the Valuation tab: its sale and documents. */
const ON_VALUATION = ['soldOn', 'proceeds', 'saleFees', 'receiptIds'];

/**
 * The tab a refused field is on: a valuation's or an improvement's on Valuation.
 * @param {Record} r @param {string | null} field @returns {string}
 */
function tabOf(r, field) {
  if (r instanceof PeriodRec) return 'general';
  if (!(r instanceof ItemRec) || ON_VALUATION.includes(field || '')) return 'valuation';
  return field === 'notes' ? 'notes' : 'general';
}

/** What an item's row shows: read from it, the dialog leaves them out (S12.18.6.5). */
const ITEM_ROW = ['name', 'metal', 'category', 'quantity', 'acquiredOn', 'costBasis'];

/** @param {{ close: (v?: any) => void, a: any, id: string | null }} p */
export function ItemDialog({ close, a, id }) {
  useDialogGuide('dialog-item');
  const res = useApi(id ? `/items/${id}` : null);
  const it = /** @type {any} */ (res.data);
  const f = useDraft(async (draft) => {
    if (!id) {
      draft.add(ItemRec, newItem(a.type, a.id));
      return;
    }
    const x = await api.get(`/items/${id}`);
    draft.load(ItemRec, {
      ...x,
      saleFees: x.sale?.fees ?? null,
      soldOn: x.sale?.soldOn ?? null,
      proceeds: x.sale?.proceeds ?? null,
      receiptIds: x.documents.map((/** @type {any} */ d) => d.id),
    });
    for (const v of x.valuations) draft.load(ValuationRec, { ...v, itemId: x.id });
    for (const m of x.improvements) draft.load(ImprovementRec, { ...m, itemId: x.id });
    for (const p of x.residencePeriods) draft.load(PeriodRec, { ...p, itemId: x.id });
  }, [id]);
  const rec = /** @type {ItemRec | undefined} */ (f.draft?.records[0]);
  const canWrite = it ? it.access.writable : true;
  const t = a.type;
  const spot = rec?.get('valuation') === 'spot';
  const [chosen, setTab] = useState('general');
  // A refusal shows at its field: its tab comes forward when the one shown has none (S1.10.6).
  const refused = (f.draft?.records || []).flatMap((r) =>
    r.errors.map((/** @type {any} */ e) => tabOf(r, e.field))
  );
  const tab = refused.length && !refused.includes(chosen) ? refused[0] : chosen;
  return html`
    <${DraftDialog} f=${f} wide close=${close} what="This item"
      title=${it ? it.name : 'Add an Item'} label=${it ? 'Save' : 'Add'}
      saveWhy=${canWrite ? null : READ_ONLY}
      saved=${(/** @type {any} */ o) => {
        toast(it ? 'Saved' : `${rec?.get('name')} added`);
        if (it) res.reload();
        close(o.saved);
      }}>
      ${rec
        ? html`
          <${Tabs} tabs=${ITEM_TABS} current=${tab} onChange=${setTab}
            off=${it ? {} : { valuation: ADD_FIRST }} />
          <${Reads} why=${!canWrite} row=${id ? ITEM_ROW : []}>
          ${tab === 'general'
            ? html`
              <${RecField} rec=${rec} name="name" label="Name" />
              ${t === 'real-estate'
                ? html`
                  <${RecField} rec=${rec} name="address" label="Address" />
                `
                : null}
              ${t === 'precious-metals'
                ? html`
                  <div class="row">
                    <${RecField} rec=${rec} name="metal" label="Metal" options=${METALS} />
                    <${RecField} rec=${rec} name="category" label="Form" id="category"
                      options=${FORMS} />
                  </div>
                `
                : t === 'collectables'
                ? html`
                  <${RecField} rec=${rec} name="category" label="Category"
                    options=${CATEGORIES} />
                `
                : null}
              ${t === 'vehicle' || t === 'other-asset'
                ? html`
                  <${RecField} rec=${rec} name="valuation" label="Valued by" id="valuation"
                    options=${VALUED_BY.filter(([k]) => k !== 'spot')} />
                `
                : null}
              ${spot
                ? html`
                  <div class="row">
                    <${RecField} rec=${rec} name="unitWeight" label="Weight per unit"
                      id="unit-weight" />
                    <${RecField} rec=${rec} name="weightUnit" label="Unit" id="weight-unit"
                      options=${UNITS} />
                  </div>
                  <div class="row">
                    <${RecField} rec=${rec} name="purity" label="Purity"
                      placeholder="ex: .9999 or 22k" />
                    <${RecField} rec=${rec} name="quantity" label="Quantity" />
                  </div>
                `
                : null}
              ${rec.get('valuation') === 'depreciation'
                ? html`
                  <${RecField} rec=${rec} name="depreciationRate" label="Depreciation per year"
                    id="depreciation-rate" />
                `
                : null}
              <div class="row">
                <${RecField} rec=${rec} name="acquiredOn" label="Date acquired" id="acquired-on"
                  type="date" />
                <${RecField} rec=${rec} name="acquiredHow" label="How acquired"
                  id="acquired-how" options=${HOW} />
              </div>
              ${rec.applies('heldFrom')
                ? html`
                  <${RecField} rec=${rec} name="heldFrom" label="Held since" id="held-from"
                    type="date" placeholder="the day acquired" />
                `
                : null}
              <div class="row">
                <${RecField} rec=${rec} name="costBasis" id="cost-basis"
                  label=${t === 'real-estate' ? 'Purchase price' : 'Cost basis'} />
                ${t === 'real-estate'
                  ? html`<${RecField} rec=${rec} name="closingCosts" label="Closing costs" />`
                  : html`<${RecField} rec=${rec} name="insuredValue" label="Insured value" />`}
              </div>
              ${t === 'real-estate' && f.draft
                ? html`<${ResidencePeriods} rec=${rec} draft=${f.draft} why=${
                  canWrite ? null : READ_ONLY
                } />`
                : null}
              ${spot
                ? html`
                  <${RecField} rec=${rec} name="sellPremium" label="Selling premium"
                    id="sell-premium" />
                `
                : null}
              ${t === 'real-estate' ? null : html`
                <div class="row">
                  <${RecField} rec=${rec} name="location" label="Where it's kept" id="location" />
                  <${RecField} rec=${rec} name="serial" id="serial"
                    label=${t === 'vehicle' ? 'VIN' : 'Serial or certificate'} />
                </div>
              `}
              <div class="row">
                <${RecField} rec=${rec} name="condition" label="Condition or grade"
                  id="condition" />
                <${RecField} rec=${rec} name="policy" label="Insurance policy" id="policy" />
              </div>
              ${t === 'vehicle' || t === 'other-asset' || t === 'collectables'
                ? html`
                  <${RecField} rec=${rec} name="personalUse" label="Used personally" />
                `
                : null}
            `
            : tab === 'notes'
            ? html`<${RecField} rec=${rec} name="notes" label="Notes" rows=${12} />`
            : null}
          </${Reads}>
          ${tab === 'valuation' && it && f.draft
            ? html`<${Side} a=${a} it=${it} rec=${rec} draft=${f.draft} />`
            : null}
        `
        : null}
    </${DraftDialog}>
  `;
}

/**
 * Beside the item's fields: its value and basis as saved, and what belongs to it, edited in
 * the dialog's draft.
 * @param {{ a: any, it: any, rec: ItemRec, draft: import('../app/draft.js').Draft }} p
 */
function Side({ a, it, rec, draft }) {
  return html`
    <div>
      <${History} id=${it.id} />
      <div class="list-item"><span class="grow dim">Value</span><b><${Amt} v=${it.value}
        cents=${false} /></b></div>
      ${it.valuation === 'spot'
        ? html`<p class="small dim">${quantity(it.fineOunces)} fine oz × ${
          it.spot
            ? html`<${Amt} v=${it.spot} /> spot on ${date(it.spotAsOf)}`
            : 'spot, once a price is in'
        }${num(it.sellPremium) ? ` · ${it.sellPremium}% when selling` : ''}</p>`
        : null}
      <div class="list-item"><span class="grow dim">Cost basis</span><${Amt} v=${it.basis}
        cents=${false} /></div>
      ${it.loans.map((/** @type {any} */ l) =>
        html`<div class="list-item"><span class="grow dim">Secures</span><a
          href=${`/ui/accounts/${l.accountId}`}>${l.name}</a>${' '}<${Amt} v=${l.owed}
          cents=${false} /></div>`
      )}
      ${it.equity != null
        ? html`
          <div
            class="list-item"><span class="grow dim">Equity</span><${Amt} v=${it
              .equity} cents=${false} /></div>
        `
        : null}
      ${rec.get('valuation') === 'spot'
        ? null
        : html`<${Valuations} it=${it} rec=${rec} draft=${draft} />`}
      ${a.type === 'real-estate'
        ? html`<${Improvements} it=${it} rec=${rec} draft=${draft} />`
        : null}
      <${Documents} it=${it} rec=${rec} />
      <${SaleCard} it=${it} rec=${rec} />
    </div>
  `;
}

/** "You and Jane", "Jane, John and Ann". */
const AND = new Intl.ListFormat('en', { style: 'long', type: 'conjunction' });

/**
 * A home's residence periods (S1.10.4, S8.13): each one person's span of it as their main
 * home. The same span for several people is one line, removed whole; a span is added for the
 * people chosen, a period each, in the dialog's draft. A line opened is changed for the people
 * left chosen, each their own period; one unticked keeps theirs, so one moving out is one edit.
 * @param {{ rec: ItemRec, draft: import('../app/draft.js').Draft, why: string | null }} p
 */
function ResidencePeriods({ rec, draft, why }) {
  const people = useList('/persons');
  const list = /** @type {any[]} */ (people.data) || [];
  const me = list.find((p) => p.relation === 'you');
  const [f, setF] = useState({ from: '', to: '', who: /** @type {string[] | null} */ (null) });
  // The line opened to change, or none: adding.
  const [open, setOpen] = useState(/** @type {PeriodRec[] | null} */ (null));
  // Until someone is chosen, the one adding it.
  const who = f.who ?? (me ? [me.id] : []);
  const rows = /** @type {PeriodRec[]} */ (
    draft.records.filter((r) => r instanceof PeriodRec && !r.removed)
  );
  // A person the reader isn't shared is named all the same, by the period's own name (R3.14).
  const named = (/** @type {string} */ id) => {
    const p = list.find((x) => x.id === id);
    if (p) return p.relation === 'you' ? 'You' : p.name;
    return rows.find((r) => r.get('personId') === id)?.get('personName') || '';
  };
  const chosen = [...list.map((p) => p.id), ...who.filter((id) => !list.some((p) => p.id === id))];
  /** @type {Map<string, PeriodRec[]>} */
  const spans = new Map();
  for (const p of rows) {
    const k = `${p.get('fromDate')}|${p.get('toDate') || ''}`;
    spans.set(k, [...(spans.get(k) || []), p]);
  }
  const lines = [...spans.values()].sort((x, y) =>
    x[0].get('fromDate') < y[0].get('fromDate') ? -1 : 1
  );
  const done = () => {
    setF({ from: '', to: '', who: null });
    setOpen(null);
  };
  const add = () => {
    for (const id of who) {
      const was = open?.find((p) => p.get('personId') === id);
      if (was) {
        was.set('fromDate', f.from);
        was.set('toDate', f.to || null);
      } else {
        draft.add(PeriodRec, {
          itemId: rec.id,
          personId: id,
          fromDate: f.from,
          toDate: f.to || null,
        });
      }
    }
    done();
  };
  const change = (/** @type {PeriodRec[]} */ ps) => {
    setF({
      from: ps[0].get('fromDate'),
      to: ps[0].get('toDate') || '',
      who: ps.map((p) => p.get('personId')),
    });
    setOpen(ps);
  };
  const pick = (/** @type {string} */ id) =>
    setF({ ...f, who: who.includes(id) ? who.filter((x) => x !== id) : [...who, id] });
  const span = (/** @type {PeriodRec} */ p) =>
    `${date(p.get('fromDate'))} to ${p.get('toDate') ? date(p.get('toDate')) : 'the sale'}`;
  return html`
    <h4 style=${{ margin: '14px 0 8px' }} data-help="residence-periods">Residence Periods</h4>
    ${lines.length
      ? null
      : html`<${Empty}>No periods: the years lived in are the preparer's to ask</${Empty}>`}
    ${lines.map((ps) => {
      const line = `${AND.format(ps.map((p) => named(p.get('personId'))))}, ${span(ps[0])}`;
      const errors = ps.flatMap((p) => p.errors.map((e) => e.message));
      return html`
        <div class="list-item" key=${ps[0].key}>
          <div class="grow">${line}${errors.length
            ? html`<div class="err">${[...new Set(errors)].join(' ')}</div>`
            : null}</div>
          <${Action} class="icon-btn" why=${why} aria-label=${'Change ' + line}
            onClick=${() => change(ps)}>
            <${Icon} name="pencil" />
            </${Action}>
            <${Action} class="icon-btn" why=${why} aria-label=${'Remove ' + line}
              onClick=${() => ps.forEach((p) => draft.remove(p))}>
              <${Icon} name="x" />
              </${Action}>
              </div>
      `;
    })}
    ${why
      ? html`<${Action} class="btn sm" why=${why}><${Icon} name="plus" /> Add Period</${Action}>`
      : html`
        <${Field} label="Who" help="residence-periods">
          <div class="chips" role="group" aria-label="Who">${chosen.map((id) =>
            html`
              <button type="button" class=${'chip' + (who.includes(id) ? ' on' : '')}
                aria-pressed=${who.includes(id) ? 'true' : 'false'}
                onClick=${() => pick(id)}>${named(id)}</button>
            `
          )}</div>
          </${Field}>
          <div class="row">
            <${Field} label="Main home from" help="residence-periods" id="lived-from">
              <${TypedInput} kind="date" value=${f.from}
                onInput=${(/** @type {string} */ x) => setF({ ...f, from: x })} />
              </${Field}>
              <${Field} label="Until" help="residence-periods" id="lived-until">
                <${TypedInput} kind="date" value=${f.to} placeholder="the sale"
                  onInput=${(/** @type {string} */ x) => setF({ ...f, to: x })} />
                </${Field}>
                </div>
                ${open
                  ? html`
                    <button type="button" class="btn sm" disabled=${!f.from || !who.length}
                      onClick=${add}>Change Period</button>
                    <button type="button" class="btn sm" onClick=${done}>Cancel</button>
                  `
                  : html`
                    <button type="button" class="btn sm" disabled=${!f.from || !who.length}
                      onClick=${add}><${Icon} name="plus" /> Add Period</button>
                  `}
      `}
  `;
}

/**
 * Its value at each month's end since it was acquired, asked only when the Valuation tab
 * opens (S1.10.6).
 * @param {{ id: string }} p
 */
function History({ id }) {
  const res = useApi(`/items/${id}/history`);
  const h = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!h) return html`<${Loading} lines=${3} />`;
  return html`
    <${TimeChart} label="Its value at each month's end" series=${[
      { name: 'Value', color: '--accent', area: true, points: h.points },
    ]} />
  `;
}

/** @param {{ it: any, rec: ItemRec, draft: import('../app/draft.js').Draft }} p */
function Valuations({ it, rec, draft }) {
  const fmt = useFormats();
  const [f, setF] = useState({ date: fmt.today(), value: '', source: 'estimate' });
  const rows = /** @type {ValuationRec[]} */ (
    draft.records.filter((r) => r instanceof ValuationRec && !r.removed)
  ).sort((x, y) => (x.get('date') < y.get('date') ? 1 : -1));
  const add = () => {
    const v = draft.add(ValuationRec, { itemId: rec.id, date: f.date, source: f.source });
    v.input('value', f.value);
    setF({ ...f, value: '' });
  };
  return html`
    <h4 style=${{ margin: '14px 0 8px' }} data-help="valuations">Valuations</h4>
    ${rows.length
      ? rows.map((v) =>
        html`<div class="list-item" key=${v.key}><div class="grow"><${Amt} v=${v.get('value')}
          cents=${false} /><div class="small dim">${SOURCE[v.get('source')]} · ${
          date(v.get('date'))
        }${
          v.errors.length
            ? html`<div class="err">${v.errors.map((e) => e.message).join(' ')}</div>`
            : null
        }</div></div>${html`
          <${Action} class="icon-btn" why=${whyRead(it)} aria-label=${`Remove the ${
            date(v.get('date'))
          } valuation`} onClick=${() => draft.remove(v)}>
            <${Icon} name="x" />
            </${Action}>
        `}</div>`
      )
      : html`<${Empty}>No valuations yet</${Empty}>`}
    ${!it.access.writable
      ? html`<${Action} class="btn sm" why=${READ_ONLY}><${Icon} name="plus" /> Add a
        Valuation</${Action}>`
      : html`
        <div class="row">
          <${Field} label="Value" help="valuations" id="valuation-value">
            <${TypedInput} kind="money" value=${f.value}
              onInput=${(/** @type {string} */ x) => setF({ ...f, value: x })} />
            </${Field}>
            <${Field} label="On" help="valuations" id="valuation-date">
              <${TypedInput} kind="date" value=${f.date} onInput=${(/** @type {string} */ x) =>
                setF({ ...f, date: x })} />
              </${Field}>
              </div>
              <div class="row">
                <${Field} label="Source" help="valuations" id="valuation-source"><${Select}
            value=${f.source} options=${SOURCES} onChange=${(/** @type {string} */ x) =>
              setF({ ...f, source: x })} /></${Field}><button type="button" class="btn sm"
            style=${{ alignSelf: 'end' }} disabled=${!clean(f.value)} onClick=${add}><${Icon}
            name="plus" /> Add</button></div>
      `}
  `;
}

/** @param {{ it: any, rec: ItemRec, draft: import('../app/draft.js').Draft }} p */
function Improvements({ it, rec, draft }) {
  const fmt = useFormats();
  const [f, setF] = useState({ date: fmt.today(), description: '', amount: '' });
  const rows = /** @type {ImprovementRec[]} */ (
    draft.records.filter((r) => r instanceof ImprovementRec && !r.removed)
  );
  const add = () => {
    const m = draft.add(ImprovementRec, {
      itemId: rec.id,
      date: f.date,
      description: f.description,
    });
    m.input('amount', f.amount);
    setF({ ...f, description: '', amount: '' });
  };
  return html`
    <h4 style=${{ margin: '14px 0 8px' }} data-help="improvements">Improvements</h4>
    ${rows.map((m) =>
      html`
        <div class="list-item" key=${m.key}>
          <div class="grow">${m.get('description')}<div
          class="small dim">${date(m.get('date'))}${m.errors.length
            ? html`<div class="err">${m.errors.map((e) => e.message).join(' ')}</div>`
            : null}</div></div>
          <${Amt} v=${m.get('amount')} cents=${false} />
          <${Action} class="icon-btn" why=${whyRead(it)}
            aria-label=${'Remove ' + m.get('description')} onClick=${() => draft.remove(m)}>
            <${Icon}
              name="x" />
            </${Action}>
            </div>
      `
    )}
    ${!it.access.writable
      ? html`<${Action} class="btn sm" why=${READ_ONLY}><${Icon} name="plus" /> Add
        Improvement</${Action}>`
      : html`
        <${Field} label="What was done" help="improvements" id="improvement-description">
          <${Input} value=${f.description}
            onInput=${(/** @type {string} */ x) => setF({ ...f, description: x })} />
          </${Field}>
          <div class="row">
            <${Field} label="Cost" help="improvements" id="improvement-amount">
              <${TypedInput} kind="money" value=${f.amount}
                onInput=${(/** @type {string} */ x) => setF({ ...f, amount: x })} />
              </${Field}>
              <${Field} label="On" help="improvements" id="improvement-date">
                <${TypedInput} kind="date" value=${f.date} onInput=${(/** @type {string} */ x) =>
                  setF({ ...f, date: x })} />
                </${Field}>
                </div>
                <button type="button" class="btn sm" disabled=${!f
                  .description} onClick=${add}><${Icon}
          name="plus" /> Add Improvement</button>
      `}
  `;
}

/**
 * Photos and documents kept with the item: each upload is a receipt of its own, saved at
 * once (S12.15.7), and kept with the item when the dialog saves.
 * @param {{ it: any, rec: ItemRec }} p
 */
function Documents({ it, rec }) {
  const [busy, setBusy] = useState(false);
  const [names, setNames] = useState(
    /** @type {{ [id: string]: string }} */ (Object.fromEntries(
      it.documents.map((/** @type {any} */ d) => [d.id, d.fileName]),
    )),
  );
  const ids = /** @type {string[]} */ (rec.get('receiptIds') || []);
  const send = async (/** @type {FileList} */ files) => {
    setBusy(true);
    try {
      const made = await uploadAll(files);
      setNames({ ...names, ...Object.fromEntries(made.map((r) => [r.id, r.fileName])) });
      rec.set('receiptIds', [...ids, ...made.map((r) => r.id)]);
    } finally {
      setBusy(false);
    }
  };
  return html`
    <h4 style=${{ margin: '14px 0 8px' }} data-help="photos-and-documents">Photos and Documents</h4>
    ${ids.length
      ? ids.map((id) =>
        html`
          <div
            class="list-item"><span class="grow"><${Icon} name="clip" /> ${names[id] ||
              'A file'}</span><${Action} class="icon-btn" why=${whyRead(it)}
              aria-label=${'Remove ' + (names[id] || '')}
              onClick=${() => rec.set('receiptIds', ids.filter((x) => x !== id))}><${Icon}
              name="x" /></${Action}></div>
        `
      )
      : html`<${Empty}>No documents yet</${Empty}>`}
    ${rec.error('receiptIds') ? html`<div class="err">${rec.error('receiptIds')}</div>` : null}
    ${!it.access.writable
      ? html`<${Action} class="btn sm" why=${READ_ONLY}><${Icon} name="upload" /> Add</${Action}>`
      : html`
        <label class="btn sm" for="f-item-files"><${Icon} name="upload" /> ${busy
          ? 'Uploading…'
          : 'Add'}</label><input
          id="f-item-files" class="sr-only" type="file" multiple
          accept=${ACCEPT} data-help="photos-and-documents" onChange=${(/** @type {any} */ e) => {
            send(e.currentTarget.files);
            e.currentTarget.value = '';
          }} />
      `}
  `;
}

/**
 * The item's sale (S1.10.5): recorded or undone in the draft, saved with the item.
 * @param {{ it: any, rec: ItemRec }} p
 */
function SaleCard({ it, rec }) {
  const fmt = useFormats();
  const s = it.sale;
  const sold = rec.get('soldOn') != null;
  if (s && sold && !rec.isChanged('soldOn')) {
    return html`
      <h4 style=${{ margin: '14px 0 8px' }} data-help="sale">Sold</h4>
      <div class="list-item"><span class="grow dim">On</span>${date(s.soldOn)}</div>
      <div class="list-item"><span class="grow dim">Proceeds, less fees</span><${Amt}
        v=${dec(s.proceeds).sub(dec(s.fees))} /></div>
      <div
        class="list-item"><span class="grow dim">${dec(s.gain).isNegative()
          ? 'Loss'
          : 'Gain'}</span><${Amt} v=${s.gain} signed /></div>
      ${s.collectable || !s.deductible
        ? html`<div class="toolbar">${
          s.collectable ? html`<${StatePill} why=${COLLECTABLE}>collectable</${StatePill}>` : null
        }${
          !s.deductible ? html`<${StatePill} why=${PERSONAL}>personal</${StatePill}>` : null
        }</div>`
        : null}
      <${Action} class="btn sm" why=${whyRead(it)} onClick=${() => {
        rec.set('soldOn', null);
        rec.set('proceeds', null);
        rec.set('saleFees', null);
      }}>Undo the Sale</${Action}>
    `;
  }
  if (!sold || !it.access.writable) {
    return html`
      ${s ? html`<${Attention}>The sale is undone when you save.</${Attention}>` : null}
      <div
        class="toolbar mt">
        <${Action} class="btn sm" why=${whyRead(it)}
          onClick=${() => rec.set('soldOn', fmt.today())}>Record the Sale…</${Action}></div>
    `;
  }
  return html`
    <h4 style=${{ margin: '14px 0 8px' }} data-help="sale">Sale</h4>
    <div class="row">
      <${Field} label="Sold on" help="sale" id="sold-on" error=${rec.error('soldOn')}>
        <${RecField} rec=${rec} name="soldOn" bare label="Sold on" type="date" />
        </${Field}>
        <${Field} label="Proceeds" help="sale" id="proceeds" error=${rec.error('proceeds')}>
          <${RecField} rec=${rec} name="proceeds" bare label="Proceeds" />
          </${Field}>
          </div>
          <${Field} label="Fees" help="sale" id="sale-fees" error=${rec.error('saleFees')}>
            <${RecField} rec=${rec} name="saleFees" bare label="Fees" />
            </${Field}>
  `;
}
