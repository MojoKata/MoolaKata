// Corporate actions (requirements S2.4): a split, a symbol change, a spin-off or a merger on
// a holding, its lots reshaped or moved with their days held, never sold and bought again.
// The action is a record of its own; the transactions it makes are made from it.
import { useEffect } from 'preact/hooks';
import { html } from '../app/html.js';
import { Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { useApi } from '../app/hooks.js';
import { DraftDialog, RecField, useDraft } from './draft-form.js';
import { useDialogGuide } from './help.js';
import { Field, Select } from './fields.js';
import { today } from '../app/format.js';

const KINDS = [
  ['split', 'Split or reverse split'],
  ['symbol-change', 'Symbol change'],
  ['spin-off', 'Spin-off'],
  ['merger', 'Merger'],
];

/** A corporate action as its dialog's draft makes it; each figure applies to its kinds. */
class ActionRec extends Record {
  /** @override */
  static prefix = 'CorpA';
  /** @override */
  static fields = FIELDS.CorporateActionRecord;
  /** @override */
  static defaults = {
    kind: 'split',
    ratio: null,
    newSymbol: null,
    basisShare: null,
    cashPerShare: null,
    newPrice: null,
  };
  /** @override */
  static rules = {
    newSymbol: { when: (/** @type {ActionRec} */ r) => r.get('kind') !== 'split' },
    // A merger paid all in cash (no new symbol) gives no shares.
    ratio: {
      when: (/** @type {ActionRec} */ r) =>
        r.get('kind') !== 'symbol-change' && !(r.get('kind') === 'merger' && !r.get('newSymbol')),
    },
    basisShare: { when: (/** @type {ActionRec} */ r) => r.get('kind') === 'spin-off' },
    cashPerShare: { when: (/** @type {ActionRec} */ r) => r.get('kind') === 'merger' },
    newPrice: {
      when: (/** @type {ActionRec} */ r) =>
        r.get('kind') === 'merger' && !!r.get('newSymbol') && !!r.get('cashPerShare'),
    },
  };
}

/** @param {{ close: (v?: any) => void, accountId?: string }} p */
export function CorporateAction({ close, accountId }) {
  useDialogGuide('dialog-corporate-action');
  const pos = useApi('/positions');
  const held = (/** @type {any[]} */ ((/** @type {any} */ (pos.data))?.open) || []).filter((
    p,
  ) =>
    p.instrumentClass !== 'option' && p.side === 'long' && (!accountId || p.accountId === accountId)
  );
  const f = useDraft((draft) => {
    draft.add(ActionRec, { date: today() });
  }, [accountId]);
  const rec = /** @type {ActionRec | undefined} */ (f.draft?.records[0]);
  const key = (/** @type {any} */ p) => p.accountId + p.instrumentId;
  const choose = (/** @type {any} */ p) => {
    rec?.set('accountId', p.accountId);
    rec?.set('instrumentId', p.instrumentId);
  };
  // The first holding the list offers, until another is chosen.
  const first = held[0];
  useEffect(() => {
    if (rec && !rec.get('instrumentId') && first) choose(first);
  }, [rec, first && key(first)]);
  const chosen = held.find((p) =>
    p.accountId === rec?.get('accountId') && p.instrumentId === rec?.get('instrumentId')
  );
  return html`
    <${DraftDialog} f=${f} title="Record a corporate action" close=${close}
      what="This corporate action" label="Record it" done="Corporate action recorded"
      disabled=${!chosen}>
      ${rec
        ? html`
          <${Field} label="Holding" error=${rec.error('instrumentId') || rec.error('accountId')}>
            <${Select} value=${chosen ? key(chosen) : ''} onChange=${(/** @type {string} */ v) => {
              const p = held.find((x) => key(x) === v);
              if (p) choose(p);
            }} options=${held.map((p) => [key(p), `${p.symbol} in ${p.accountName}`])} />
            </${Field}>
            <div class="row">
              <${RecField} rec=${rec} name="kind" label="Action" options=${KINDS} />
              <${RecField} rec=${rec} name="date" label="Date" type="date" />
            </div>
            <${RecField} rec=${rec} name="newSymbol" label="New symbol" placeholder="META"
              hint=${rec.get('kind') === 'merger' ? 'Empty for a merger paid all in cash.' : ''} />
            <${RecField} rec=${rec} name="ratio" label="New shares for each held"
              hint=${rec.get('kind') === 'split'
                ? '2 for a 2-for-1 split, 0.1 for a 1-for-10 reverse.'
                : ''} />
            <${RecField} rec=${rec} name="basisShare" label="Basis to the new shares"
              hint="In percent, from the company's Form 8937." placeholder="13.65" />
            <${RecField} rec=${rec} name="cashPerShare" label="Cash for each share held"
              placeholder="0.00" />
            <${RecField} rec=${rec} name="newPrice" label="A new share's price that day"
              hint="The cash is a gain only as far as the gain goes, and this tells the gain." />
        `
        : null}
    </${DraftDialog}>
  `;
}
