// The tax panels (requirements S8.1–S8.13): what a tax book's accounts did in its year, for a
// preparer or tax software: the gains summary and exports, Form 8949 with wash sales, income,
// retirement, deductions, giving, education and gifts, loans and property, and what to look
// at.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { useApi } from '../app/hooks.js';
import { api } from '../api/client.js';
import { date, money, quantity } from '../app/format.js';
import { Amt } from './amount.js';
import { Chips, Empty, Failed, Loading } from './bits.js';
import { Icon } from './icon.js';
import { Dec, dec, num } from '../app/dec.js';

export const PANEL_TABS = /** @type {[string, string][]} */ ([
  ['gains', 'Capital gains (8949)'],
  ['income', 'Income'],
  ['retirement', 'Retirement'],
  ['deductions', 'Deductions'],
  ['giving', 'Giving'],
  ['education', 'Education and gifts'],
  ['property', 'Loans and property'],
  ['issues', 'Issues'],
]);

/** The panels, loaded once for the book. */
/** @param {{ id: string }} p */
export function usePanels({ id }) {
  return useApi(`/tax-books/${id}/panels`, {}, ['import', 'prices']);
}

/** @param {{ b: any, tab: string }} p */
export function Panel({ b, tab }) {
  const res = usePanels({ id: b.id });
  const p = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!p) return html`<${Loading} lines=${6} />`;
  return html`
    ${p.leftOut.length
      ? html`<p class="small dim">Left out of this book: ${p.leftOut.join(', ')}.</p>`
      : null}
    ${tab === 'gains' ? html`<${Gains} p=${p} />` : null}
    ${tab === 'income' ? html`<${Income} p=${p} />` : null}
    ${tab === 'retirement' ? html`<${Retirement} p=${p} />` : null}
    ${tab === 'deductions' ? html`<${Deductions} p=${p} />` : null}
    ${tab === 'giving' ? html`<${Giving} p=${p} />` : null}
    ${tab === 'education' ? html`<${Education} p=${p} />` : null}
    ${tab === 'property' ? html`<${Property} p=${p} />` : null}
    ${tab === 'issues' ? html`<${Issues} p=${p} b=${b} reload=${res.reload} />` : null}
  `;
}

/** The Summary's figures and exports. */
/** @param {{ b: any }} p */
export function SummaryFigures({ b }) {
  const res = usePanels({ id: b.id });
  const p = /** @type {any} */ (res.data);
  if (!p) return html`<${Loading} lines=${3} />`;
  const d = p.scheduleD;
  const base = `/ui/api/tax-books/${b.id}/exports`;
  return html`
    <div class="grid g4">
      <div class="card kpi">
        <div class="label">Net capital gain or loss</div>
        <div class="value">
          <${Amt}
            v=${dec(d.shortTerm).add(dec(d.longTerm))} signed cents=${false} />
        </div>
        <div
          class="delta dim">short <${Amt} v=${d.shortTerm} signed cents=${false} /> · long <${Amt}
          v=${d.longTerm} signed cents=${false} /></div>
      </div>
      <div class="card kpi">
        <div class="label">Dividends</div>
        <div class="value">
          <${Amt}
            v=${p.income.ordinary} cents=${false} />
        </div>
        <div class="delta dim">qualified <${Amt}
          v=${p.income.qualified} cents=${false} /></div>
      </div>
      <div class="card kpi">
        <div class="label">Interest</div>
        <div class="value">
          <${Amt}
            v=${p.income.interestTotal} cents=${false} />
        </div>
        <div class="delta dim">${p.income.interest
          .length} payer${p.income.interest.length === 1 ? '' : 's'}</div>
      </div>
      <div class="card kpi">
        <div class="label">Charitable gifts</div>
        <div class="value">
          <${Amt}
            v=${p.giving.deductibleTotal} cents=${false} />
        </div>
        <div class="delta">${p.giving
            .missingAcks
          ? html`<${Icon} name="alert" /> ${p.giving.missingAcks} acknowledgement${
            p.giving
                .missingAcks === 1
              ? ''
              : 's'
          } missing`
          : html`<span class="dim">deductible</span>`}</div>
      </div>
    </div>
    <div class="card mt">
      <h3 data-help="exports">Exports</h3>
      <div class="list-item"><div class="grow">Form 8949 and Schedule D (CSV)<div
        class="small dim">Every sale in the book's taxable accounts, by box</div></div><a
        class="btn sm" href=${`${base}/8949.csv`} download><${Icon} name="download" /> CSV</a></div>
      <div class="list-item"><div class="grow">TXF for tax software<div class="small dim">TurboTax,
        H&R Block and others import it</div></div><a class="btn sm" href=${`${base}/moolakata.txf`}
        download><${Icon} name="download" /> TXF</a></div>
      ${txfLeftOut(p.txfLeftOut)}
      <div class="list-item"><div class="grow">Summary for a preparer (PDF)<div class="small dim">What
        each panel holds, with its sources</div></div><a class="btn sm"
        href=${`${base}/summary.pdf`} download><${Icon} name="download" /> PDF</a></div>
      <p class="small dim">${p.covers}</p>
    </div>
  `;
}

/**
 * The sales TXF can't carry, counted by why (S8.2): "TXF leaves out 4 sales (3 digital
 * assets, 1 collectable): enter them from the CSV."
 * @param {{ digital: number, collectable: number, personalUse: number }} n
 */
function txfLeftOut(n) {
  const kinds = /** @type {[number, string, string][]} */ ([
    [n.digital, 'digital asset', 'digital assets'],
    [n.collectable, 'collectable', 'collectables'],
    [n.personalUse, 'personal-use loss', 'personal-use losses'],
  ]).filter(([c]) => c);
  const all = kinds.reduce((t, [c]) => t + c, 0);
  if (!all) return null;
  const why = kinds.map(([c, one, many]) => `${c} ${c === 1 ? one : many}`).join(', ');
  return html`
    <div class="notice warn" role="status">
      <${Icon} name="alert" />
      <div>TXF leaves out ${all} sale${all === 1 ? '' : 's'} (${why}): enter ${all === 1
        ? 'it'
        : 'them'} from the CSV.</div>
    </div>
  `;
}

/** @param {{ p: any }} p */
function Gains({ p }) {
  const [term, setTerm] = useState('all');
  const rows = p.rows.filter((/** @type {any} */ r) =>
    term === 'all' || (term === 'long') === r.longTerm
  );
  const d = p.scheduleD;
  return html`
    <div class="grid g-main">
      <div class="card"
        style=${{ padding: '4px 8px' }}><div class="toolbar" style=${{
          padding: '8px 8px 0',
        }}><h3 style=${{ margin: 0 }}>Form 8949</h3><span class="spacer"></span><${Chips}
        label="Term" value=${term} onChange=${setTerm} options=${[
          ['all', 'All'],
          ['short', 'Short term'],
          ['long', 'Long term'],
        ]} /></div>
        ${rows.length
          ? html`
            <div class="table-wrap">
              <table class="t">
                <caption class="sr-only">Form 8949 rows</caption>
                <thead>
                  <tr>
                    <th>Box</th>
                    <th>Description</th>
                    <th>Acquired</th>
                    <th>Sold</th>
                    <th class="num">Proceeds</th>
                    <th class="num">Basis</th>
                    <th>Code</th>
                    <th class="num">Adjustment</th>
                    <th class="num">Gain or loss</th>
                  </tr>
                </thead>
                <tbody>${rows.map((/** @type {any} */ r) =>
                  html`
                    <tr>
                      <td>${r.box}</td>
                      <td>${r.description}<div class="small dim">${r.account}${r
                          .collectable
                        ? ' · collectable'
                        : ''}</div></td>
                      <td class="small">${r.acquired ? date(r.acquired) : 'Various'}</td>
                      <td class="small">${date(r.sold)}</td>
                      <td class="num">
                        <${Amt} v=${r.proceeds} />
                      </td>
                      <td class="num">${r.basis ? html`<${Amt} v=${r.basis} />` : html`
                        <span
                          class="pill warn">missing</span>
                      `}</td>
                      <td>${r.code || ''}</td>
                      <td class="num">${num(r.adjustment)
                        ? html`<${Amt} v=${r.adjustment} />`
                        : html`<span class="dim">—</span>`}</td>
                      <td class="num">${r.gain ? html`<${Amt} v=${r.gain} signed />` : '—'}</td>
                    </tr>
                  `
                )}</tbody>
              </table>
            </div>
          `
          : html`<${Empty}>No sales in ${p.year}.</${Empty}>`}
      </div>
      <div class="grid" style=${{ alignContent: 'start' }}>
        <div class="card facts"><h3>Schedule D</h3>${d.boxes.map((/** @type {any} */ x) =>
          html`<div class="list-item"><span class="grow dim">Box ${x.box}</span><${Amt} v=${x.gain}
            signed /></div>`
        )}
          <div class="list-item"><span class="grow dim">Short term</span><${Amt} v=${d.shortTerm}
            signed /></div>
          <div class="list-item"><span class="grow dim">Long term</span><${Amt} v=${d.longTerm}
            signed /></div>
          ${num(d.collectables)
            ? html`<div class="list-item"><span class="grow dim">Of it, collectables</span><${Amt}
              v=${d.collectables} signed /></div>`
            : null}
          ${num(d.carryoverShort) || num(d.carryoverLong)
            ? html`<div class="list-item"><span class="grow dim">Loss carried from last year</span><${Amt}
              v=${dec(d.carryoverShort).add(dec(d.carryoverLong))} /></div>`
            : null}
        </div>
        <div class="card"><h3 data-help="wash-sales">Wash sales</h3>${p.washes.length
          ? p.washes.map((/** @type {any} */ w) =>
            html`<div class="list-item"><div class="grow">${w.symbol} sold ${date(w.sold)}<div
              class="small dim">${w.account} · replaced ${
              date(w.replacedOn)
            } in ${w.replacementAccount} (${quantity(w.replacementQty)} shares)${
              w.adjustedBasis ? html`, basis now <${Amt} v=${w.adjustedBasis} />` : ''
            }</div></div>${
              w.review
                ? html`<span class="pill warn" title="An option on the same underlying">review</span>`
                : html`
                  <span
                    class="small"><span class="pill warn">W</span> <${Amt} v=${w
                      .disallowed} /> of <${Amt} v=${w.loss} /></span>
                `
            }</div>`
          )
          : html`<p class="small dim">None found: no loss sale was replaced within 30 days.</p>`}
          <p class="small dim">Same instrument, in any of the filers' accounts (IRAs included)
            and a spouse's. Whether others are substantially identical is the preparer's call.</p>
        </div>
      </div>
    </div>
  `;
}

/** @param {{ p: any }} p */
function Income({ p }) {
  const i = p.income;
  return html`
    <div class="grid g2">
      <div class="card"><h3>Interest (1099-INT)</h3>${i.interest.length
        ? i.interest.map((/** @type {any} */ x) =>
          html`<div class="list-item"><span class="grow">${x.label}</span><${Amt} v=${x.amount} /></div>`
        )
        : html`<p class="small dim">No interest in ${p.year}.</p>`}</div>
      <div class="card facts"><h3>Dividends (1099-DIV)</h3>
        <div class="list-item"><span class="grow dim">Ordinary (1a)</span><${Amt} v=${i
          .ordinary} /></div>
        <div class="list-item"><span class="grow dim">Qualified (1b)</span><${Amt} v=${i
          .qualified} /></div>
        <div class="list-item"><span class="grow dim">Capital-gain distributions (2a)</span><${Amt}
          v=${i.capitalGainDistributions} /></div>
        <div class="list-item"><span class="grow dim">Return of capital</span><${Amt}
          v=${i.returnOfCapital} /></div>
        ${i.dividendsByPayer.map((/** @type {any} */ x) =>
          html`<div class="list-item"><span class="grow small">${x.label}</span><${Amt}
            v=${x.amount} /></div>`
        )}
      </div>
    </div>
  `;
}

/** @param {{ p: any }} p */
function Retirement({ p }) {
  const r = p.retirement;
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}><h3 style=${{ padding: '8px 8px 0' }}>
      Contributions against the limits</h3>${r.contributions.length
        ? html`
          <div class="table-wrap">
            <table class="t">
              <caption class="sr-only">Contributions</caption>
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Owner</th>
                  <th class="num">Contributed</th>
                  <th class="num">Limit</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>${r.contributions.map((/** @type {any} */ c) =>
                html`
                  <tr>
                    <td>${c.account}<div class="small dim">${c.kind}</div></td>
                    <td>${c.owner}</td>
                    <td class="num">
                      <${Amt} v=${c.contributed} />${c.across
                        ? html`<div class="small dim">${html`<${Amt} v=${c.personTotal} />`}
                          across their ${c.across}</div>`
                        : null}
                    </td>
                    <td class="num">${c.limit
                      ? html`<${Amt} v=${c.limit} cents=${false} />`
                      : '—'}${c.note ? html`<div class="small dim">${c.note}</div>` : null}</td>
                    <td>${c.over ? html`<span class="pill warn">over the limit</span>` : null}</td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        `
        : html`<p class="small dim">No retirement accounts in this book.</p>`}</div>
    <div class="grid g2 mt">
      <div class="card"><h3>Distributions</h3>${r.distributions.length
        ? r.distributions.map((/** @type {any} */ x) =>
          html`<div class="list-item"><span class="grow">${x.label}</span><${Amt} v=${x.amount} /></div>`
        )
        : html`<p class="small dim">None in ${p.year}.</p>`}
        ${r.basis8606
          ? html`<p class="small dim">Form 8606 basis carried from last year: <${Amt}
            v=${r.basis8606} />, for a backdoor Roth's conversion.</p>`
          : null}</div>
      <div class="card"><h3 data-help="rmds">Required minimum distributions</h3>${r.rmds.length
        ? r.rmds.map((/** @type {any} */ x) =>
          html`
            <div class="list-item">
              <div
                class="grow">${x.account}<div class="small dim">${x
                  .owner}, ${x.age}: <${Amt} v=${x
                  .balance} cents=${false} /> at the end of last year ÷
                        ${x.factor}</div></div>
              <${Amt} v=${x.due} />
            </div>
          `
        )
        : html`<p class="small dim">None due: no owner has reached the RMD age.</p>`}</div>
    </div>
  `;
}

/** @param {{ p: any }} p */
function Deductions({ p }) {
  const total = Dec.sum(p.estimated.map((/** @type {any} */ q) => dec(q.amount)));
  return html`
    <div class="grid g-main">
      <div class="card" style=${{ padding: '4px 8px' }}><h3 style=${{ padding: '8px 8px 0' }}>
        Tax-tagged categories</h3>${p.deductions.length
          ? html`
            <div class="table-wrap">
              <table class="t">
                <caption class="sr-only">Deductions</caption>
                <thead>
                  <tr>
                    <th>Category</th>
                    <th class="num">Total</th>
                    <th class="num">Transactions</th>
                    <th>Receipts</th>
                  </tr>
                </thead>
                <tbody>${p.deductions.map((/** @type {any} */ d) =>
                  html`
                    <tr>
                      <td>${d.label}</td>
                      <td class="num">
                        <${Amt} v=${d.total} />
                      </td>
                      <td class="num">${d.count}</td>
                      <td><span class=${'pill ' +
                        (d.withReceipts === d.count ? 'ok' : 'warn')}><${Icon} name="clip" /> ${d
                        .withReceipts} of ${d.count}</span></td>
                    </tr>
                  `
                )}</tbody>
              </table>
            </div>
          `
          : html`<p class="small dim">No transactions in tax-tagged categories.</p>`}</div>
      <div class="card"><h3 data-help="estimated-payments">Estimated payments</h3>${p.estimated
          .length
        ? p.estimated.map((/** @type {any} */ q) =>
          html`<div class="list-item"><span class="grow">${q.jurisdiction} · Q${q.quarter}</span><${Amt}
            v=${q.amount} /></div>`
        )
        : html`<p class="small dim">None recorded in the filings.</p>`}
        ${p.lastYearTax
          ? html`<p class="small dim">Last year's total tax: <${Amt} v=${p.lastYearTax}
            cents=${false} />; paid in ${p.year} so far: ${money(total, { cents: false })}.</p>`
          : null}</div>
    </div>
    <div class="card mt"><h3 data-help="dependents-ages">Dependents' ages on Dec 31</h3>${p
        .dependents.length
      ? p.dependents.map((/** @type {any} */ d) =>
        html`
          <div
            class="list-item"><div class="grow">${d.name}${d.relation
              ? html`<span class="dim"> · ${d.relation}</span>`
              : null}${d.agesOut.length
              ? html`<div class="small dim">${d.agesOut.join('; ')}</div>`
              : null}</div><span class="small">${d.age == null
              ? 'age unknown'
              : `${d.age}${d.under13 ? ' · under 13' : ''}${
                d.under17 ? ' · under 17' : ''
              }`}</span></div>
        `
      )
      : html`<p class="small dim">No dependents in this book: add them on the Summary.</p>`}
      <p class="small dim">Under 17 for the child tax credit, under 13 for the childcare credit.
        Whether each one qualifies is the preparer's to decide.</p></div>
  `;
}

/** @param {{ p: any }} p */
function Giving({ p }) {
  const g = p.giving;
  const table = (/** @type {any[]} */ rows) =>
    html`
      <div class="table-wrap">
        <table class="t">
          <caption class="sr-only">Donations</caption>
          <thead>
            <tr>
              <th>Date</th>
              <th>Organisation</th>
              <th>Type</th>
              <th class="num">Amount</th>
              <th>Acknowledgement</th>
            </tr>
          </thead>
          <tbody>${rows.map((d) =>
            html`
              <tr>
                <td class="small dim">${date(d.date)}</td>
                <td>${d.name}</td>
                <td class="small">${d
                  .kindLabel}</td>
                <td class="num">
                  <${Amt} v=${d.amount} />
                </td>
                <td>${d.acknowledged
                  ? html`<span class="small"><${Icon} name="clip" /> received</span>`
                  : d.needsAck
                  ? html`<span class="pill warn">missing</span>`
                  : html`<span class="dim">—</span>`}</td>
              </tr>
            `
          )}</tbody>
        </table>
      </div>
    `;
  return html`
    ${g.notes.map((/** @type {string} */ n) =>
      html`
        <div class="notice mb">
          <${Icon} name="info" />
          <div>${n}</div>
        </div>
      `
    )}
    <div class="card" style=${{ padding: '4px 8px' }}><h3 style=${{ padding: '8px 8px 0' }}>
      Deductible<span class="spacer"></span><${Amt} v=${g.deductibleTotal} /></h3>${g.deductible
          .length
        ? table(g.deductible)
        : html`<p class="small dim">None.</p>`}</div>
    ${g.apart.length
      ? html`
        <div class="card mt"
          style=${{ padding: '4px 8px' }}><h3 style=${{
            padding: '8px 8px 0',
          }}>Not deducted</h3>${table(g.apart)}<p class="small dim" style=${{
            padding: '0 8px',
          }}>QCDs (excluded from income instead), grants from a donor-advised fund, and gifts to
                organisations that aren't deductible.</p></div>
      `
      : null}
  `;
}

/** @param {{ p: any }} p */
function Education({ p }) {
  return html`
    <div class="grid g2">
      <div class="card"><h3>529 plans</h3>${p.education.length
        ? p.education.map((/** @type {any} */ e) =>
          html`<h4 style=${{ margin: '8px 0 4px' }}>${e.account} · ${e.beneficiary}</h4>
            ${
            e.contributions.map((/** @type {any} */ c) =>
              html`<div class="list-item"><span class="grow dim">From ${c.label}</span><${Amt}
                v=${c.amount} /></div>`
            )
          }
            ${
            e.stateDeduction
              ? html`<div class="list-item"><span class="grow dim">State deduction expected</span><${Amt}
                v=${e.stateDeduction} cents=${false} /></div>`
              : null
          }
            <div class="list-item"><span class="grow dim">Distributions (1099-Q)</span><${Amt}
              v=${e.distributions} /></div>
            <div class="list-item"><span class="grow dim">Qualified expenses</span><${Amt}
              v=${e.expenses} /></div>
            ${
            num(e.notCovered)
              ? html`<div class="list-item"><span class="grow dim">Not covered</span><span
                class="pill warn"><${Amt} v=${e.notCovered} /></span></div>`
              : null
          }`
        )
        : html`<p class="small dim">No 529 plans in this book.</p>`}
        <p class="small dim">The earnings in what isn't covered may be taxable, with a 10%
          additional tax; the preparer applies the rules with education credits.</p>
        ${p.students.length
          ? html`<h4 style=${{ margin: '12px 0 4px' }}>Dependent students</h4>${
            p.students.map((
              /** @type {any} */ x,
            ) =>
              html`<div class="list-item"><div class="grow">${x.name}<div class="small dim">529
              withdrawals for them: ${money(x.withdrawals529)}</div></div><span class=${
                'pill ' +
                (x.received1098T ? 'ok' : 'warn')
              }>1098-T ${x.received1098T ? 'received' : 'missing'}</span></div>`
            )
          }`
          : null}</div>
      <div class="card"><h3 data-help="form-709">Gifts (Form 709)</h3>${p.giftTax.length
        ? p.giftTax.map((/** @type {any} */ x) =>
          html`
            <div class="list-item">
              <div class="grow">${x.giver} to ${x.person}<div
                        class="small dim">above the <${Amt} v=${x
                          .exclusion} cents=${false} /> exclusion</div></div>
              <${Amt}
                v=${x.given} />
            </div>
          `
        )
        : html`<p class="small dim">No one received more than the annual exclusion.</p>`}
        ${p.elections.map((/** @type {string} */ x) => html`<p class="small dim">${x}</p>`)}</div>
    </div>
  `;
}

/** @param {{ p: any }} p */
function Property({ p }) {
  const sold = p.rows.filter((/** @type {any} */ r) => !r.description.match(/^\d/));
  return html`
    <div class="grid g2">
      <div class="card"><h3>Loans (1098, 1098-E)</h3>${p.loans.length
        ? p.loans.map((/** @type {any} */ l) =>
          html`
            <h4 style=${{ margin: '8px 0 4px' }}>${l.account} · ${l.form}${l.securedBy
              ? html`<span class="small dim"> · ${l.securedBy}</span>`
              : null}</h4>
                        <div
              class="list-item"><span class="grow dim">Interest</span><${Amt} v=${l
                .interest} /></div>
                        ${num(l.pmi)
                          ? html`<div class="list-item"><span class="grow dim">PMI</span><${Amt} v=${l.pmi} /></div>`
                          : null}
                        ${num(l.propertyTax)
                          ? html`<div class="list-item"><span class="grow dim">Property tax through escrow</span><${Amt}
                v=${l.propertyTax} /></div>`
                          : null}
          `
        )
        : html`<p class="small dim">No loans in this book.</p>`}
        <p class="small dim">Computed from the payments' splits; compare with the 1098 when it
          arrives.</p></div>
      <div class="card"><h3>Physical assets sold</h3>${sold.length
        ? sold.map((/** @type {any} */ r) =>
          html`
            <div class="list-item">
              <div class="grow">${r.description}<div class="small dim">${date(
                r.sold,
              )}${r.collectable ? ' · collectable' : ''}${r.code === 'L'
                ? ' · a loss on personal-use property, not deductible'
                : ''}</div></div>
              <${Amt} v=${r.gain || '0'} signed />
            </div>
          `
        )
        : html`<p class="small dim">Nothing sold in ${p.year}.</p>`}
        ${p.residences.map((/** @type {any} */ h) =>
          html`
            <div class="notice mt">
              <${Icon} name="home" />
              <div>${h.name}, your primary residence,
                        sold ${date(h.sold)} after ${h.yearsOwned} years: a gain of <${Amt} v=${h
                          .gain} />. The
                        exclusion is the preparer's to apply.</div>
            </div>
          `
        )}</div>
    </div>
  `;
}

/**
 * An edit made anyway since the federal return was filed offers an amended return, or No
 * amendment needed (S8.15), to those who may write.
 * @param {{ p: any, b: any, reload: () => void }} props
 */
function Issues({ p, b, reload }) {
  const waive = () => api.post(`/tax-books/${b.id}/no-amendment`).then(reload);
  return html`
    <div class="card">${p.issues.length
      ? p.issues.map((/** @type {any} */ i) =>
        html`
          <div
            class="list-item"><${Icon} name="alert" /><span class="grow">${i.text}</span>${i
                    .kind === 'changed-after-filing' && b.access.writable
              ? html`
                <a class="btn sm" href="/ui/taxes/filings">Add an amended return</a><button class="btn sm"
                  onClick=${waive}>No amendment needed</button>
              `
              : i.link
              ? html`<a class="small" href=${i.link}>Look</a>`
              : null}</div>
        `
      )
      : html`<p class="small dim">Nothing to look at: every sale has a lot and a basis.</p>`}</div>
  `;
}
