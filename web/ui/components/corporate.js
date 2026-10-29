// Corporate actions (requirements S2.4): a split, a symbol change, a spin-off or a merger on
// a holding, its lots reshaped or moved with their days held, never sold and bought again.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useSubmit } from '../app/hooks.js';
import { Dialog } from './dialog.js';
import { useDialogGuide } from './help.js';
import { errAt, Field, FormError, Input, Select } from './fields.js';
import { toast } from './toast.js';
import { today } from '../app/format.js';

const clean = (/** @type {string} */ s) => (s ? String(s).replace(/[$,%\s]/g, '') : '');
const KINDS = [
  ['split', 'Split or reverse split'],
  ['symbol-change', 'Symbol change'],
  ['spin-off', 'Spin-off'],
  ['merger', 'Merger'],
];

/** @param {{ close: (v?: any) => void, accountId?: string }} p */
export function CorporateAction({ close, accountId }) {
  useDialogGuide('dialog-corporate-action');
  const pos = useApi('/positions');
  const held = (/** @type {any[]} */ ((/** @type {any} */ (pos.data))?.open) || []).filter((
    p,
  ) =>
    p.instrumentClass !== 'option' && p.side === 'long' && (!accountId || p.accountId === accountId)
  );
  const [f, setF] = useState({
    holding: '',
    kind: 'split',
    date: today(),
    ratio: '',
    newSymbol: '',
    basisShare: '',
    cashPerShare: '',
    newPrice: '',
  });
  const [start] = useState(() => JSON.stringify(f));
  const set = (/** @type {string} */ k) => (/** @type {any} */ x) => setF({ ...f, [k]: x });
  const pick = held.find((p) => p.accountId + p.instrumentId === f.holding) || held[0];
  const save = useSubmit(async (/** @type {boolean} */ confirm = false) => {
    const out = await api.post(`/accounts/${pick?.accountId}/corporate-actions`, {
      kind: f.kind,
      date: f.date,
      instrumentId: pick?.instrumentId,
      ratio: clean(f.ratio) || null,
      newSymbol: f.newSymbol || null,
      basisShare: clean(f.basisShare) || null,
      cashPerShare: clean(f.cashPerShare) || null,
      newPrice: clean(f.newPrice) || null,
    }, confirm ? { params: { confirm: true } } : {});
    toast(`${out[out.length - 1].payee} recorded`);
    close(out);
  });
  const e = save.error;
  const ask = e?.code === 'closed-year'; // a year whose return is filed (S2.8)
  const k = f.kind;
  return html`
    <${Dialog} title="Record a corporate action" close=${close}
      onSubmit=${() => save.run(ask).catch(() => {})}
      changed=${() => JSON.stringify(f) !== start}
      footer=${html`
        <button type="button" class="btn" data-cancel>Cancel</button><button class="btn primary"
          disabled=${save.busy || !pick}
        >${ask ? 'Record it anyway' : 'Record it'}</button>
      `}>
      <${Field} label="Holding" error=${errAt(e, 'instrumentId')}>
        <${Select} value=${pick ? pick.accountId + pick.instrumentId : ''} onChange=${set(
          'holding',
        )}
          options=${held.map((
            p,
          ) => [p.accountId + p.instrumentId, `${p.symbol} in ${p.accountName}`])} />
        </${Field}>
        <div class="row">
          <${Field} label="Action" error=${errAt(e, 'kind')}>
            <${Select} value=${k} onChange=${set('kind')} options=${KINDS} />
            </${Field}>
            <${Field} label="Date" error=${errAt(e, 'date')}>
          <${Input} type="date" value=${f.date} onInput=${set('date')} required />
        </${Field}>
      </div>
      ${k !== 'split'
        ? html`
          <${Field} label="New symbol" error=${errAt(e, 'newSymbol')}
            hint=${k === 'merger' ? 'Empty for a merger paid all in cash.' : ''}>
            <${Input} value=${f.newSymbol} onInput=${set('newSymbol')} placeholder="META" />
            </${Field}>
        `
        : null}
      ${k !== 'symbol-change' && !(k === 'merger' && !f.newSymbol)
        ? html`
          <${Field} label="New shares for each held" error=${errAt(e, 'ratio')}
            hint=${k === 'split' ? '2 for a 2-for-1 split, 0.1 for a 1-for-10 reverse.' : ''}>
            <${Input} value=${f.ratio} onInput=${set('ratio')} inputmode="decimal" />
            </${Field}>
        `
        : null}
      ${k === 'spin-off'
        ? html`
          <${Field} label="Basis to the new shares" error=${errAt(e, 'basisShare')}
            hint="In percent, from the company's Form 8937.">
            <${Input} value=${f.basisShare} onInput=${set('basisShare')} inputmode="decimal"
              placeholder="13.65" />
            </${Field}>
        `
        : null}
      ${k === 'merger'
        ? html`
          <${Field} label="Cash for each share held" error=${errAt(e, 'cashPerShare')}>
            <${Input} value=${f.cashPerShare} onInput=${set('cashPerShare')} inputmode="decimal"
              placeholder="0.00" />
            </${Field}>
        `
        : null}
      ${k === 'merger' && f.newSymbol && clean(f.cashPerShare)
        ? html`
          <${Field} label="A new share's price that day" error=${errAt(e, 'newPrice')}
            hint="The cash is a gain only as far as the gain goes, and this tells the gain.">
            <${Input} value=${f.newPrice} onInput=${set('newPrice')} inputmode="decimal" />
            </${Field}>
        `
        : null}
      <${FormError} error=${e} shown=${[
        'instrumentId',
        'kind',
        'date',
        'newSymbol',
        'ratio',
        'basisShare',
        'cashPerShare',
        'newPrice',
      ]} />
    </${Dialog}>
  `;
}
