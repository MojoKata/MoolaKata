// Strategies (requirements S3.5): legs held together, shown as one with their figures at
// expiry and capital at risk now and at open; the groupings and rolls proposed; a strategy's
// settings (its name, cash-secured, the margin for undefined risk) and undoing it. Grouping is a
// label: each leg keeps its own lots, gains and wash sales.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useSubmit } from '../app/hooks.js';
import { date, quantity, today } from '../app/format.js';
import { Amt } from './amount.js';
import { Dec, dec } from '../app/dec.js';
import { Empty, Failed, Loading } from './bits.js';
import { Dialog, openDialog } from './dialog.js';
import { errAt, Field, FormError, Input, Select } from './fields.js';
import { Record as Rec } from '../app/draft.js';
import { DraftDialog, RecField, saveNow, useDraft } from './draft-form.js';
import { FIELDS } from '../api/fields.js';
import { useDialogGuide } from './help.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';
import { confirmAction } from './confirm.js';

/** "Short 1 SPY 20NOV26 540 P", or "Long 100 AAPL". @param {any} x */
const legLine = (x) => {
  const n = dec(x.quantity);
  if (n.isZero()) return `${x.symbol} · closed ${x.closedOn ? date(x.closedOn) : ''}`;
  return `${n.isNegative() ? 'Short' : 'Long'} ${quantity(n.abs())} ${x.symbol}`;
};

/** @param {any} v @param {boolean} cents */
const money = (v, cents = false) =>
  v == null ? html`<span class="dim">unlimited</span>` : html`<${Amt} v=${v} cents=${cents} />`;

export function Strategies() {
  const res = useApi('/positions/strategies', {}, ['import', 'prices']);
  const v = /** @type {any} */ (res.data);
  const act = useSubmit(async (/** @type {() => Promise<any>} */ f) => {
    await f();
    res.reload();
  });
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} lines=${4} />`;
  // Grouped as proposed, or the proposal turned down: a strategy made, dismissed or not.
  const group = (/** @type {any} */ p, /** @type {boolean} */ dismissed) =>
    act.run(() =>
      saveNow((d) =>
        d.add(StrategyRec, {
          accountId: p.accountId,
          legs: p.legs.map((/** @type {any} */ l) => ({
            instrumentId: l.instrumentId,
            quantity: l.quantity || null,
          })),
          dismissed,
        })
      ).then(() => toast(dismissed ? 'Left as they are' : `Grouped as a ${p.shape.toLowerCase()}`))
    ).catch((e) => toast(e.message));
  const roll = (/** @type {any} */ p, /** @type {boolean} */ keep) => {
    const st = v.strategies.find((/** @type {any} */ x) => x.id === p.strategyId);
    if (!st) return;
    act.run(() =>
      api.post(
        `/strategies/${st.id}/roll`,
        keep ? { roll: [{ instrumentId: p.legs[0].instrumentId }] } : {
          declineRoll: [p.legs[0].instrumentId],
        },
      ).then(() => toast(keep ? 'Rolled into the strategy' : 'Left on its own'))
    ).catch((e) => toast(e.message));
  };
  const open = v.strategies.filter((/** @type {any} */ x) => !x.closedOn);
  const closed = v.strategies.filter((/** @type {any} */ x) => x.closedOn);
  const total = (/** @type {string} */ k) =>
    Dec.sum(
      open.filter((/** @type {any} */ x) => x[k] != null).map((/** @type {any} */ x) => dec(x[k])),
    );
  // One strategy's unlimited risk makes the total unlimited, never left out of it (S3.5.5).
  const risk = (/** @type {string} */ k) =>
    open.some((/** @type {any} */ x) => x[k] == null) ? money(null) : money(String(total(k)));
  return html`
    ${v.proposals.map((/** @type {any} */ p) =>
      html`
        <div class="notice mb" role="status">
          <${Icon} name="info" />
          <div>${p.kind === 'roll'
            ? html`
              ${p.legs[0].symbol} opened ${date(p.openedOn)} in ${p.accountName}, the day a leg of
                        <b>${p.shape}</b> on ${p
                          .underlying} closed: a roll? <button type="button" class="btn sm
                        primary" disabled=${act.busy} onClick=${() =>
                          roll(p, true)}>Keep it in the strategy</button> <button
                type="button" class="btn sm"
                disabled=${act.busy} onClick=${() => roll(p, false)}>Not a roll</button>
            `
            : html`
              ${p.legs.length} legs on ${p.underlying} ${p.kind === 'covered-call'
                ? 'in'
                : `opened ${date(p.openedOn)} in`} ${p.accountName} look like a <b>${p.shape
                .toLowerCase()}</b>: ${p.legs.map((/** @type {any} */ l) =>
                  l.quantity ? `${quantity(l.quantity)} ${l.symbol}` : l.symbol
                ).join(', ')}. <button
                type="button" class="btn sm primary" disabled=${act.busy}
                onClick=${() =>
                  group(p, false)}>Group them</button> <button type="button" class="btn sm"
                disabled=${act.busy} onClick=${() => group(p, true)}>Not a strategy</button>
            `}</div>
        </div>
      `
    )}
    ${v.strategies.length
      ? html`
        <div class="card" style=${{ padding: '4px 8px' }}>
          <div class="table-wrap">
            <table class="t">
                <caption class="sr-only">Strategies</caption>
                <thead><tr><th>Strategy</th><th class="num">Credit</th><th class="num">P/L</th><th
                  class="num">Max profit</th><th class="num">Max loss</th><th>Breakeven</th><th class="num"
                  data-help="at-risk-now">At risk now</th><th class="num" data-help="at-open">At open</th><th
                  ></th></tr></thead>
                <tbody>${[...open, ...closed].map((/** @type {any} */ x) =>
                  html`
                    <tr class=${x.closedOn ? 'dim' : ''}>
                      <td
                        style=${{ whiteSpace: 'nowrap' }}><b>${x.name}</b> · ${x
                          .underlying}${x.name !==
                            x.shape
                          ? html`
                            <span class="small dim">(${x.shape})</span>
                          `
                          : null}<div class="small dim">${x.accountName} · opened ${date(
                            x.openedOn,
                          )}${x
                            .closedOn
                          ? ` · closed ${date(x.closedOn)}`
                          : ''}</div>${x.legs.map((/** @type {any} */ l) =>
                            html`<div class="small dim">└ ${legLine(l)}</div>`
                          )}</td>
                      <td class="num">
                        <${Amt} v=${x.credit} signed cents=${false} />
                      </td>
                      <td class="num">${x.pl == null
                        ? '—'
                        : html`<${Amt} v=${x.pl} signed cents=${false} />`}</td>
                      <td class="num">${x.expiryKnown
                        ? money(x.maxProfit)
                        : html`<span class="dim">—</span>`}</td>
                      <td class="num">${x.expiryKnown
                        ? money(x.maxLoss)
                        : html`<span class="dim">—</span>`}</td>
                      <td class="small">${x.expiryKnown
                        ? x.breakevens.map((/** @type {any} */ b) => String(b)).join(' · ') || '—'
                        : 'P/L only: it rests on volatility'}</td>
                      <td class="num">${x.closedOn ? '—' : money(x.capitalAtRiskNow)}</td>
                      <td class="num">${money(x.capitalAtRiskAtOpen)}${x.returnPct != null
                        ? html`<div class="small">${x.returnPct}%</div>`
                        : null}</td>
                      <td>${x.access.writable
                        ? html`<button type="button" class="btn sm" onClick=${() =>
                          openDialog(StrategyDialog, { x }).then((ok) =>
                            ok && res.reload()
                          )}>Edit…</button>`
                        : null}</td>
                    </tr>
                  `
                )}</tbody>
                ${open.length
                  ? html`
                    <tfoot>
                      <tr>
                        <td>Open strategies</td>
                        <td></td>
                        <td class="num">
                          <${Amt} v=${String(
                            total('pl'),
                          )} signed cents=${false} />
                        </td>
                        <td colspan="3"></td>
                        <td class="num">${risk('capitalAtRiskNow')}</td>
                        <td class="num">${risk('capitalAtRiskAtOpen')}</td>
                        <td></td>
                      </tr>
                    </tfoot>
                  `
                  : null}
              </table>
          </div>
        </div>
      `
      : html`<${Empty}>No strategies yet. Legs opened together are offered here; or select legs on
        the Open tab and Group them.</${Empty}>`}
    <div class="toolbar mt"><span class="small dim">Grouping is a label: each leg keeps its own
      lots, gains and wash sales. Capital at risk is the most the strategy can lose at expiry; for
      undefined risk, the margin you type.</span><span class="spacer"></span><button type="button"
      class="btn sm" onClick=${() =>
        openDialog(AdjustDialog, {}).then((x) => x && res.reload())}>An underlying was
      adjusted…</button></div>
  `;
}

/** "150 XYZ + 20 ABC" as the deliverable's parts. @param {string} text */
const parts = (text) =>
  text.split(/[+,]/).map((p) => p.trim()).filter(Boolean).map((p) => {
    const m = p.match(/^([\d.,]+)\s+([A-Za-z.]+)$/);
    return m
      ? { shares: m[1].replace(/,/g, ''), symbol: m[2].toUpperCase() }
      : { shares: '', symbol: p };
  });

/**
 * The OCC adjusted an underlying's options (S3.10.2): each open contract's new root, strike and
 * deliverable, from its information memo. The lots carry over: nothing is sold.
 * @param {{ close: (v?: any) => void }} p
 */
function AdjustDialog({ close }) {
  useDialogGuide('dialog-option-adjust');
  const res = useApi('/options/adjustable');
  const groups = /** @type {any[] | null} */ ((/** @type {any} */ (res.data))?.items ?? null);
  const [under, setUnder] = useState('');
  const [rows, setRows] = useState(/** @type {Record<string, any>} */ ({}));
  const [day, setDay] = useState(today());
  const g = groups?.find((x) => x.underlyingId === under) || groups?.[0];
  const row = (/** @type {any} */ c) =>
    rows[c.instrumentId] || {
      root: `${g.underlying}1`,
      strike: String(c.strike),
      deliverable: `100 ${g.underlying}`,
      cash: '0',
    };
  const set = (/** @type {string} */ id, /** @type {string} */ k) => (/** @type {string} */ v) =>
    setRows({
      ...rows,
      [id]: { ...row(g.contracts.find((/** @type {any} */ c) => c.instrumentId === id)), [k]: v },
    });
  const save = useSubmit(async () => {
    const out = await api.post('/options/adjust', {
      date: day,
      contracts: g.contracts.map((/** @type {any} */ c) => {
        const r = row(c);
        return {
          instrumentId: c.instrumentId,
          root: r.root,
          strike: r.strike,
          deliverable: parts(r.deliverable),
          cash: r.cash || '0',
        };
      }),
    });
    toast(`${out.contracts} contract${out.contracts === 1 ? '' : 's'} adjusted`);
    close(out);
  });
  if (!groups) return null;
  return html`
    <${Dialog} title=${g
      ? `Options on ${g.underlying} after a corporate action`
      : 'Adjusted options'}
      wide close=${close} onSubmit=${() => g && save.run().catch(() => {})}
      note=${g
        ? html`
          <a href=${`https://infomemo.theocc.com/infomemo/search?symbol=${
            encodeURIComponent(g.underlying)
          }`}
            target="_blank" rel="noopener">Find the OCC's memo for ${g.underlying}</a>
        `
        : null}
      footer=${g
        ? html`<button class="btn primary" disabled=${save.busy}>${`Adjust ${g.contracts.length} contract${
          g.contracts.length === 1 ? '' : 's'
        }`}</button>`
        : null}>
      ${!g ? html`<p>No options are open in accounts you can change.</p>` : html`
        <p class="small dim" style=${{ marginTop: 0 }}>A split that isn't a whole number, a
          merger, a spin-off or a large special dividend changes each open contract's root and
          deliverable, as the OCC's information memo says. The lots carry over: nothing is
          sold. A whole-number split needs none of this.</p>
        <div class="row">
          <${Field} label="Underlying" id="adjust-underlying">
            <${Select} value=${g.underlyingId} onChange=${setUnder}
              options=${groups.map((x) => [x.underlyingId, x.underlying])} />
            </${Field}>
            <${Field} label="Effective" id="adjust-date" error=${errAt(save.error, 'date')}>
              <${Input} type="date" value=${day} onInput=${setDay} />
              </${Field}>
              </div>
              <div class="table-wrap">
                <table class="t">
                  <thead>
                    <tr>
                      <th>Contract</th>
                      <th
                        data-help="new-root">New root</th>
                      <th class="num">Strike</th>
                      <th
                        data-help="deliverable">Deliverable</th>
                      <th class="num">Cash</th>
                    </tr>
                  </thead>
                  <tbody>${g
                    .contracts.map((/** @type {any} */ c, /** @type {number} */ i) => {
                      const r = row(c);
                      return html`
                        <tr>
                          <td><b>${c.symbol}</b><div class="small dim">${c.held.join(
                            '; ',
                          )}</div></td>
                          <td><input class="in" style=${{ maxWidth: '90px' }}
                                        aria-label="New root" value=${r.root} onInput=${(
                                          /** @type {any} */ e,
                                        ) =>
                                          set(c.instrumentId, 'root')(
                                            e.currentTarget.value,
                                          )} />${errAt(
                                            save.error,
                                            `contracts.${i}.root`,
                                          )
                                          ? html`<div class="err">${
                                            errAt(save.error, `contracts.${i}.root`)
                                          }</div>`
                                          : null}</td>
                          <td class="num"><input class="in num" style=${{ maxWidth: '90px' }}
                                        aria-label="Strike" value=${r.strike} onInput=${(
                                          /** @type {any} */ e,
                                        ) =>
                                          set(c.instrumentId, 'strike')(
                                            e.currentTarget.value,
                                          )} /></td>
                          <td><input class="in"
                                        style=${{
                                          maxWidth: '180px',
                                        }} aria-label="Deliverable" value=${r.deliverable}
                                        placeholder="150 XYZ + 20 ABC" onInput=${(
                                          /** @type {any} */ e,
                                        ) =>
                                          set(c.instrumentId, 'deliverable')(
                                            e.currentTarget.value,
                                          )} /></td>
                          <td class="num"
                          ><input class="in num" style=${{ maxWidth: '90px' }} aria-label="Cash"
                                        value=${r.cash} onInput=${(/** @type {any} */ e) =>
                                          set(c.instrumentId, 'cash')(
                                            e.currentTarget.value,
                                          )} /></td>
                        </tr>
                      `;
                    })}</tbody>
                </table>
              </div>
              <${FormError} error=${save.error} shown=${['date']} />
      `}
    </${Dialog}>
  `;
}

/** A strategy (S3.5), as its dialog's draft edits it: deleted, it is ungrouped. */
class StrategyRec extends Rec {
  /** @override */
  static prefix = 'Strat';
  /** @override */
  static fields = FIELDS.StrategyRecord;
  /** @override */
  static defaults = {
    dismissed: false,
    name: null,
    cashSecured: false,
    marginRequirement: null,
  };
}

/** A strategy's name, cash-secured tick and margin, or undo it. @param {{ close: (v?: any) => void, x: any }} p */
function StrategyDialog({ close, x }) {
  useDialogGuide('dialog-strategy');
  // Its name as given: none when it goes by its shape.
  const f = useDraft((draft) => {
    draft.load(StrategyRec, { ...x, name: x.name === x.shape ? null : x.name });
  }, [x.id]);
  const rec = /** @type {StrategyRec | undefined} */ (f.draft?.records[0]);
  const shortPut = x.legs.some((/** @type {any} */ l) =>
    l.kind === 'put' && dec(l.quantity).isNegative()
  );
  return html`
    <${DraftDialog} f=${f} title=${`${x.name} · ${x.underlying}`} close=${close}
      what="This strategy"
      done=${rec?.removed ? 'Ungrouped: the legs stand on their own' : 'Saved'}
      extra=${({ save }) =>
        html`
          <button type="button" class="btn danger" disabled=${save.busy || !rec}
            onClick=${async () => {
              const draft = f.draft;
              if (!rec || !draft) return;
              const sure = await confirmAction({
                title: 'Ungroup this strategy?',
                detail: 'Its legs stay, each on its own.',
                yes: 'Yes, ungroup',
              });
              if (!sure) return;
              draft.remove(rec);
              const r = await save.run().catch(() => null);
              if (r?.status !== 'asks' && r?.status !== 'saved') draft.unremove(rec);
            }}>Ungroup</button><span class="spacer"></span>
        `}>
      ${rec
        ? html`
          <${RecField} rec=${rec} name="name" label="Name" id="strategy-name"
            hint=${`Empty: its shape, ${x.shape.toLowerCase()}.`} />
          ${shortPut
            ? html`
              <${RecField} rec=${rec} name="cashSecured" label="Cash-secured"
                hint="The cash to buy the shares is set aside." />
            `
            : null}
          <${RecField} rec=${rec} name="marginRequirement" label="Margin requirement"
            id="margin-requirement" placeholder="unlimited"
            hint="Your broker's, for a strategy whose loss has no limit: its capital at risk." />
          <p class="small dim">Ungrouping leaves each leg as it is: its lots, gains and history
            don't change.</p>
        `
        : null}
    </${DraftDialog}>
  `;
}

/**
 * Group the legs selected on the Open tab.
 * @param {{ rows: any[], done: () => void }} p
 */
export function GroupButton({ rows, done }) {
  const act = useSubmit(async () => {
    await saveNow((d) =>
      d.add(StrategyRec, {
        accountId: rows[0].accountId,
        legs: rows.map((r) => ({
          instrumentId: r.instrumentId,
          quantity: r.instrumentClass === 'option' ? null : r.quantity,
        })),
      })
    );
    toast('Grouped as a strategy');
    done();
  });
  const one = new Set(rows.map((r) => r.accountId)).size === 1;
  return html`
    <button type="button" class="btn" disabled=${act.busy || !rows.length || !one}
      title=${one ? undefined : 'Legs in one account'}
      onClick=${() => act.run().catch((e) => toast(e.message))}><${Icon} name="plus" /> Group ${rows
        .length} leg${rows.length === 1 ? '' : 's'}</button>
  `;
}
