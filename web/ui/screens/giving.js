// Giving (requirements S7.9, S12.2.9): the year's target and progress, donations,
// organisations, and the donor-advised fund.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { useApi, useList } from '../app/hooks.js';
import { date, money, quantity, thisYear, today } from '../app/format.js';
import { useTitle } from '../components/frame.js';
import { useDialogGuide, useGuide } from '../components/help.js';
import { Amt } from '../components/amount.js';
import { Chips, Empty, Failed, Loading, Tabs } from '../components/bits.js';
import { openDialog } from '../components/dialog.js';
import { Field, Seg, Select } from '../components/fields.js';
import { Icon } from '../components/icon.js';
import { ShareDialog } from '../components/share.js';
import { ACCEPT, uploadAll } from '../components/receipt.js';
import { TimeChart } from '../charts/chart.js';
import { Dec, dec, num } from '../app/dec.js';
import { Record as Rec } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { DraftDialog, RecField, useDraft } from '../components/draft-form.js';
import { confirmAction } from '../components/confirm.js';

const TABS = /** @type {[string, string][]} */ ([
  ['overview', 'Overview'],
  ['donations', 'Donations'],
  ['organisations', 'Organisations'],
  ['fund', 'Donor-advised fund'],
]);
const KINDS = /** @type {[string, string][]} */ ([
  ['cash', 'Cash (card, cheque, transfer)'],
  ['goods', 'Goods, at fair value'],
  ['securities', 'Appreciated shares'],
  ['qcd', 'QCD from an IRA'],
  ['daf-contribution', 'Into a donor-advised fund'],
  ['daf-grant', 'Grant from a donor-advised fund'],
]);

/** @param {{ tab?: string }} p */
export default function Giving({ tab }) {
  const current = TABS.some(([k]) => k === tab) ? /** @type {string} */ (tab) : 'overview';
  const now = thisYear();
  const [year, setYear] = useState(String(now));
  useTitle('Giving');
  useGuide('giving-' + current);
  const res = useApi('/giving', { year }, ['import']);
  const v = /** @type {any} */ (res.data);
  return html`
    <div class="toolbar"><${Tabs} tabs=${TABS} current=${current} base="/ui/giving" /><span
      class="spacer"></span><${Chips} label="Year" value=${year} onChange=${setYear}
      options=${[now - 1, now].map((y) => [String(y), String(y)])} /></div>
    ${res.error
      ? html`<${Failed} error=${res.error} />`
      : !v
      ? html`<${Loading} lines=${6} />`
      : current === 'overview'
      ? html`<${Overview} v=${v} reload=${res.reload} />`
      : current === 'donations'
      ? html`<${Donations} year=${year} reload=${res.reload} />`
      : current === 'organisations'
      ? html`<${Organisations} />`
      : html`<${Fund} v=${v} year=${year} />`}
  `;
}

/** @param {{ v: any, reload: () => void }} p */
function Overview({ v, reload }) {
  const plan = v.plan;
  const editPlan = () => openDialog(PlanDialog, { v }).then((x) => x && reload());
  const record = () => openDialog(DonationDialog, {}).then((x) => x && reload());
  const behind = dec(v.pace).sub(dec(v.given));
  const months = v.byMonth.map((/** @type {string} */ x, /** @type {number} */ i) => [
    new Date(Date.UTC(v.year, i + 1, 0)).toISOString().slice(0, 10),
    x,
  ]).filter((/** @type {[string, string]} */ p) => p[0] <= today() || v.year < thisYear());
  const pace = months.map((/** @type {[string, string]} */ [d]) => {
    const start = Date.UTC(v.year, 0, 1);
    const days = (Date.parse(d) - start) / 86400000 + 1;
    return [d, String(Math.round(num(v.target) * days / 365))];
  });
  if (!plan) {
    return html`<${Empty}>No giving plan for ${v.year} yet. Set a target, as a percentage of
      income or an amount, to follow your giving against it.
      <div class="mt"><button type="button" class="btn primary" onClick=${editPlan}>Set a
        target</button></div></${Empty}>
      ${
      num(v.given)
        ? html`<p class="small dim">Given so far in ${v.year}: <${Amt} v=${v.given} />.</p>`
        : null
    }`;
  }
  const most = Math.max(1, ...v.byCause.map((/** @type {any} */ c) => num(c.amount)));
  return html`
    <div class="grid g4">
      <div class="card kpi" data-help="target">
        <div class="label">Target ${v.year}</div>
        <div class="value">
          <${Amt} v=${v.target} cents=${false} />
        </div>
        <div class="delta dim">${plan.targetKind === 'percent'
          ? html`${String(plan.percent)}% of <${Amt} v=${v.income} cents=${false} /> ${
            {
              'take-home': 'take-home pay',
              gross: 'gross income',
              agi: 'estimated AGI',
            }[/** @type {'take-home'|'gross'|'agi'} */ (plan.incomeBasis)]
          }`
          : 'a fixed amount'} · ${!plan.access.writable
          ? html`shared by ${plan.ownerName}`
          : html`<a href="#" onClick=${(/** @type {Event} */ e) => {
            e.preventDefault();
            editPlan();
          }}>Edit</a>`}${plan.access.shareable
          ? html`
            · <a href="#" onClick=${(/** @type {Event} */ e) => {
              e.preventDefault();
              openDialog(ShareDialog, {
                kind: 'giving-plan',
                id: plan.id,
                name: `Giving plan ${plan.year}`,
              });
            }}>Share</a>
          `
          : null}</div>
      </div>
      <div class="card kpi" data-help="given">
        <div class="label">Given</div>
        <div class="value">
          <${Amt} v=${v.given} cents=${false} />
        </div>
        <div class="bar" style=${{ marginTop: '8px' }}><i style=${{
          width: `${Math.min(100, (num(v.given) / Math.max(1, num(v.target))) * 100)}%`,
        }}></i></div>
      </div>
      <div class="card kpi" data-help="pace">
        <div class="label">Pace to date</div>
        <div class="value">
          <${Amt} v=${v.pace} cents=${false} />
        </div>
        <div class="delta">${behind.gt(0)
          ? html`<span class="down"><${Amt} v=${String(behind)} cents=${false} /> behind</span>`
          : html`<span class="up"><${Amt} v=${
            String(behind.neg())
          } cents=${false} /> ahead</span>`}</div>
      </div>
      <div class="card kpi" data-help="projected">
        <div class="label">Projected year end</div>
        <div class="value">
          <${Amt} v=${v.projected} cents=${false} />
        </div>
        <div class="delta dim">with <${Amt} v=${v.pledged} cents=${false} /> of pledges due</div>
      </div>
    </div>
    ${v.missingAcks
      ? html`
        <div class="notice warn mt">
          <${Icon} name="alert" />
          <div>${v.missingAcks} donation${v
              .missingAcks === 1
            ? ''
            : 's'} of $250 or more without a written acknowledgement. <a
                href="/ui/giving/donations">See the donations</a>.</div>
        </div>
      `
      : null}
    ${v.notes.map((/** @type {string} */ n) =>
      html`
        <div class="notice mt">
          <${Icon} name="info" />
          <div>${n}</div>
        </div>
      `
    )}
    <div class="grid g-main mt">
      <div class="card">
        <h3>Given against the target<span class="spacer"></span><button
        class="btn sm primary" onClick=${record}><${Icon} name="plus" /> Record a donation</button></h3>
        <${TimeChart} label=${`Given in ${v.year} against the target`} series=${[
          { name: 'Given', color: '--hue-giving', points: months },
          { name: 'Even pace to the target', color: '--fg-muted', dash: true, points: pace },
        ]} />
        <p class="small dim">${plan.dafCounted === 'funded'
          ? 'A donor-advised fund counts when it is funded; its grants are not counted again.'
          : 'A donor-advised fund counts when it grants, not when it is funded.'}</p>
      </div>
      <div class="grid" style=${{ alignContent: 'start' }}>
        <div class="card"><h3>By cause</h3>${v.byCause.length
          ? v.byCause.map((/** @type {any} */ c) =>
            html`<div class="list-item"><div class="grow"><div class="small">${c.label}</div><div
              class="bar" style=${{ marginTop: '6px' }}><i style=${{
              width: `${(num(c.amount) / most) * 100}%`,
              background: 'var(--hue-giving)',
            }}></i></div></div><span class="num small"><${Amt} v=${c.amount}
              cents=${false} /></span></div>`
          )
          : html`<p class="small dim">Nothing given yet.</p>`}</div>
        <div class="card"><h3>Percent of income</h3>${v.history.map((/** @type {any} */ h) =>
          html`
            <div
              class="list-item"><span class="small" style=${{ width: '48px' }}>${h
                .year}</span><div class="grow"><div class="bar"><i style=${{
                width: `${Math.min(100, num(h.percent) * 5)}%`,
                background: 'var(--hue-giving)',
              }}></i></div></div><span class="num small" style=${{ width: '52px' }}>${h.percent ==
                  null
                ? '—'
                : `${h.percent}%`}</span></div>
          `
        )}</div>
        <div class="card"><h3>By organisation</h3>${v.byOrganisation.map((/** @type {any} */ o) =>
          html`<div class="list-item"><span class="grow">${o.label}</span><${Amt} v=${o.amount}
            cents=${false} /></div>`
        )}</div>
      </div>
    </div>
  `;
}

/** @param {{ year: string, reload: () => void }} p */
function Donations({ year, reload }) {
  const res = useList('/giving/donations', { year }, ['import']);
  const rows = /** @type {any[]} */ (res.data);
  const again = () => {
    res.reload();
    reload();
  };
  const record = (/** @type {any} */ from) =>
    openDialog(DonationDialog, { from }).then((x) => x && again());
  const open = (/** @type {any} */ d) =>
    d.id ? openDialog(DonationView, { d }).then((x) => x && again()) : record(d);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!rows) return html`<${Loading} />`;
  return html`
    <div class="toolbar"><span class="small dim">Donations come from transactions categorised
      Giving, or are recorded here.</span><span class="spacer"></span><button class="btn primary"
      onClick=${() => record(null)}><${Icon} name="plus" /> Record a donation</button></div>
    ${rows.length
      ? html`
        <div class="card" style=${{ padding: '4px 8px' }}>
          <div class="table-wrap">
            <table
              class="t">
              <caption class="sr-only">Donations</caption>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Organisation</th>
                  <th>Type</th>
                  <th class="num">Amount</th>
                  <th>Deductible</th>
                  <th>Acknowledgement</th>
                </tr>
              </thead>
              <tbody>${rows.map((d) =>
                html`
                  <tr class="click" tabindex="0" onClick=${() => open(d)} onKeyDown=${(
                    /** @type {KeyboardEvent} */ e,
                  ) => e.key === 'Enter' && open(d)}>
                    <td class="small dim" style=${{ whiteSpace: 'nowrap' }}>${date(d.date)}</td>
                    <td>${d.name}${d.id
                      ? null
                      : html`<div class="small dim">from a transaction</div>`}</td>
                    <td class="small">${d.kindLabel}${d.symbol
                      ? html`<div class="dim">${quantity(d.quantity)} ${d.symbol} · ${
                        d.longTerm ? 'held over a year' : 'held under a year'
                      }</div>`
                      : null}</td>
                    <td class="num">
                      <${Amt} v=${d.amount} />
                    </td>
                    <td>${d.kind === 'daf-grant'
                      ? html`<span class="small dim">a grant · not deducted again</span>`
                      : d.deductible
                      ? html`<${Icon} name="check" label="Deductible" />`
                      : html`<span class="pill">no</span>`}</td>
                    <td>${d.acknowledged
                      ? html`<span class="small"><${Icon} name="clip" /> received</span>`
                      : d.needsAck
                      ? html`<span class="pill warn">missing · needed at $250+</span>`
                      : html`<span class="dim">—</span>`}</td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        </div>
      `
      : html`<${Empty}>No donations in ${year} yet.</${Empty}>`}
  `;
}

function Organisations() {
  const res = useList('/giving/organisations');
  const rows = /** @type {any[]} */ (res.data);
  const open = (/** @type {any} */ o) =>
    openDialog(OrganisationDialog, { o }).then((x) => x && res.reload());
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!rows) return html`<${Loading} />`;
  return html`
    <div
      class="toolbar"><span class="spacer"></span><button class="btn primary" onClick=${() =>
        open(null)}><${Icon} name="plus" /> Add an organisation</button></div>
    ${rows.length
      ? html`
        <div class="card" style=${{ padding: '4px 8px' }}>
          <div class="table-wrap">
            <table
              class="t">
              <caption class="sr-only">Organisations</caption>
              <thead>
                <tr>
                  <th>Organisation</th>
                  <th>EIN</th>
                  <th>Deductible</th>
                  <th>Causes</th>
                  <th>Pledge</th>
                  <th class="num">Given this year</th>
                </tr>
              </thead>
              <tbody>${rows.map((o) =>
                html`
                  <tr class="click" tabindex="0" onClick=${() => open(o)} onKeyDown=${(
                    /** @type {KeyboardEvent} */ e,
                  ) => e.key === 'Enter' && open(o)}>
                    <td>${o.name}</td>
                    <td class="small dim" style=${{ whiteSpace: 'nowrap' }}>${o.ein ||
                      '—'}</td>
                    <td>${o.deductible
                      ? html`<${Icon} name="check" label="Deductible" />`
                      : html`<span class="pill">no</span>`}</td>
                    <td class="small">${o.causes.join(', ') ||
                      html`<span class="dim">—</span>`}</td>
                    <td class="small">${o.pledge
                      ? html`<${Amt} v=${o.pledge} cents=${false} /> a ${o.pledgeEvery}`
                      : html`<span class="dim">—</span>`}</td>
                    <td class="num">
                      <${Amt} v=${o.given} cents=${false} />
                    </td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        </div>
      `
      : html`<${Empty}>No organisations yet. Add the charities, churches and causes you give
        to, with their EIN, and any pledges.</${Empty}>`}
  `;
}

/** @param {{ v: any, year: string }} p */
function Fund({ v, year }) {
  const res = useList('/giving/donations', { year });
  const grants = (/** @type {any[]} */ (res.data) || []).filter((d) => d.kind === 'daf-grant');
  if (!v.funds.length) {
    return html`<${Empty}>No donor-advised fund. Add one as an account of type
      <b>Donor-advised fund</b>: contributions to it are deducted when made, and its grants are
      not deducted again.</${Empty}>`;
  }
  return html`
    ${v.funds.map((/** @type {any} */ f) =>
      html`
        <div class="grid g4 mt">
          <div class="card kpi">
            <div class="label">${f.name}</div>
            <div class="value">
              <${Amt}
                v=${f.balance} cents=${false} />
            </div>
            <div class="delta dim">${f.institution ||
              'the fund'} · not in net worth</div>
          </div>
          <div class="card kpi">
            <div class="label">Contributed ${v.year}</div>
            <div class="value">
              <${Amt}
                v=${f.contributed} cents=${false} />
            </div>
            <div class="delta dim">deducted this year</div>
          </div>
          <div class="card kpi">
            <div class="label">Granted ${v.year}</div>
            <div class="value">
              <${Amt}
                v=${f.granted} cents=${false} />
            </div>
            <div class="delta dim">not deducted again</div>
          </div>
          <div class="card kpi">
            <div class="label">Account</div>
            <div class="value small"><a
                  href=${`/ui/accounts/${f.accountId}`}>Holdings and transactions</a></div>
          </div>
        </div>
      `
    )}
    <div class="card mt"><h3>Grants</h3>${grants.length
      ? grants.map((g) =>
        html`
          <div
            class="list-item"><div class="grow">${g.name}<div class="small dim">${date(
              g.date,
            )}</div></div><span class=${'pill ' + (g.granted ? 'ok' : 'info')}>${g.granted
              ? 'paid'
              : 'pending'}</span> <${Amt} v=${g.amount} cents=${false} /></div>
        `
      )
      : html`<p class="small dim">No grants in ${year}.</p>`}
      <p class="small dim">${v.plan?.dafCounted === 'granted'
        ? 'This plan counts the fund toward the target when it grants.'
        : "This plan counts the fund toward the target when it's funded, so grants aren't counted again."}</p>
    </div>
  `;
}

/** A year's giving plan (S7.9.1). */
class GivingPlanRec extends Rec {
  /** @override */
  static prefix = 'GvPln';
  /** @override */
  static fields = FIELDS.GivingPlanRecord;
  /** @override */
  static defaults = {
    targetKind: 'percent',
    percent: Dec.parse('10'),
    amount: null,
    incomeBasis: 'take-home',
    income: null,
    dafCounted: 'funded',
  };
  /** @override */
  static rules = {
    percent: { when: (/** @type {GivingPlanRec} */ r) => r.get('targetKind') === 'percent' },
    amount: { when: (/** @type {GivingPlanRec} */ r) => r.get('targetKind') === 'amount' },
    income: { when: (/** @type {GivingPlanRec} */ r) => r.get('incomeBasis') !== 'take-home' },
  };
}

/** @param {{ close: (v?: any) => void, v: any }} p */
function PlanDialog({ close, v }) {
  useDialogGuide('dialog-giving-plan');
  const f = useDraft((draft) => {
    if (v.plan) draft.load(GivingPlanRec, v.plan);
    else draft.add(GivingPlanRec, { year: v.year });
  }, [v.plan?.id]);
  const rec = /** @type {GivingPlanRec | undefined} */ (f.draft?.records[0]);
  return html`
    <${DraftDialog} f=${f} title=${`Giving plan ${v.year}`} close=${close} what="This plan"
      done="Giving plan saved">
      ${rec
        ? html`
          <div class="field" data-help="target-kind" id="x-target-kind"><label>Target</label>
            <${Seg} label="Target" value=${rec.get('targetKind')} onChange=${(
              /** @type {string} */ x,
            ) => rec.set('targetKind', x)} options=${[
              ['percent', 'Percent of income'],
              ['amount', 'A fixed amount'],
            ]} /></div>
          ${rec.get('targetKind') === 'percent'
            ? html`
              <div class="row">
                <${RecField} rec=${rec} name="percent" label="Percent of income" id="percent" />
                <${RecField} rec=${rec} name="incomeBasis" label="Income" id="income-basis"
                  options=${[
                    ['take-home', 'Income transactions (take-home)'],
                    ['gross', 'Gross income, typed'],
                    ['agi', 'AGI estimate, typed'],
                  ]} />
              </div>
              <${RecField} rec=${rec} name="income" id="income"
                label=${rec.get('incomeBasis') === 'gross' ? 'Gross income' : 'AGI estimate'}
                hint="From your W-2, pay stubs or last return." />
            `
            : html`<${RecField} rec=${rec} name="amount" label="Target amount" id="amount" />`}
          <${RecField} rec=${rec} name="dafCounted" label="Count the donor-advised fund"
            id="daf-counted" hint="Either way, a dollar through the fund counts once."
            options=${[
              ['funded', 'When it is funded'],
              ['granted', 'When it grants'],
            ]} />
        `
        : null}
    </${DraftDialog}>
  `;
}

/** A donation (S7.9.2): recorded whole, then changed after the fact. */
class DonationRec extends Rec {
  /** @override */
  static prefix = 'Dnatn';
  /** @override */
  static fields = FIELDS.DonationRecord;
  /** @override */
  static defaults = {
    organisationId: null,
    amount: null,
    description: null,
    transactionId: null,
    fromAccountId: null,
    dafAccountId: null,
    lotId: null,
    quantity: null,
    acknowledged: false,
    granted: null,
    notes: null,
    receiptIds: [],
  };
  /** @override */
  static rules = {
    organisationId: {
      when: (/** @type {DonationRec} */ r) => r.get('kind') !== 'daf-contribution',
    },
    dafAccountId: {
      when: (/** @type {DonationRec} */ r) =>
        ['daf-contribution', 'daf-grant'].includes(r.get('kind')),
    },
    description: { when: (/** @type {DonationRec} */ r) => r.get('kind') === 'goods' },
    // A grant recorded is a grant made.
    granted: {
      when: (/** @type {DonationRec} */ r) => r.get('kind') === 'daf-grant',
      setWhen: (/** @type {DonationRec} */ r) =>
        r.state === 'new' && r.get('kind') === 'daf-grant' && r.get('granted') == null,
      value: true,
    },
  };
}

/** @param {{ close: (v?: any) => void, from?: any }} p */
function DonationDialog({ close, from }) {
  useDialogGuide('dialog-donation');
  const orgs = useList('/giving/organisations');
  const accounts = useList('/accounts');
  const f = useDraft((draft) => {
    const d = draft.add(DonationRec, {
      kind: 'cash',
      date: from?.date || today(),
      transactionId: from?.transactionId || null,
    });
    if (from?.amount) d.input('amount', String(from.amount));
  }, []);
  const rec = /** @type {DonationRec | undefined} */ (f.draft?.records[0]);
  // The lot chosen, with its price for the shares' market value.
  const [lot, setLot] = useState('');
  const kind = rec?.get('kind') || 'cash';
  const fromId = rec?.get('fromAccountId') || '';
  const all = /** @type {any[]} */ (accounts.data) || [];
  const writable = all.filter((a) => a.active && a.access.writable);
  const funds = writable.filter((a) => a.type === 'daf');
  const shares = kind === 'securities' ||
    (kind === 'daf-contribution' && writable.find((a) => a.id === fromId)?.investing);
  const holdings = useApi(shares && fromId ? `/accounts/${fromId}/holdings` : null);
  /** @type {[string, string][]} */
  const lots = [];
  for (const h of /** @type {any} */ (holdings.data)?.holdings || []) {
    for (const l of h.lots) {
      if (!l.lotId) continue;
      lots.push([
        `${l.lotId}|${h.price || ''}`,
        `${h.symbol} · ${quantity(l.quantity)} · bought ${date(l.acquiredOn)}${
          l.basis ? ` · basis ${money(l.basis, { cents: false })}` : ''
        }${l.longTerm ? ' · held over a year' : ''}`,
      ]);
    }
  }
  const price = lot.split('|')[1];
  const sources = kind === 'securities'
    ? writable.filter((a) => a.investing && a.type !== 'daf')
    : kind === 'qcd'
    ? writable.filter((a) => ['ira', '401k', '403b', '457b'].includes(a.type))
    : writable.filter((a) => a.type !== 'daf' && (a.group === 'banking' || a.investing));
  return html`
    <${DraftDialog} f=${f} title=${from ? `Record ${from.name}` : 'Record a donation'}
      close=${close} what="This donation" done="Donation recorded" before=${() => {
        // Shares come from a lot; money and goods from no lot.
        if (!shares && rec) rec.set('lotId', null);
        if (!shares && rec) rec.set('quantity', null);
      }}>
      ${rec
        ? html`
          <${RecField} rec=${rec} name="kind" label="Type" id="kind"
            options=${from ? KINDS.filter(([k]) => k === 'cash') : KINDS} />
          <div class="row">
            <${RecField} rec=${rec} name="organisationId" label="Organisation"
              id="organisation" options=${[
                ['', 'Choose…'],
                ...(/** @type {any[]} */ (orgs.data) || []).map((o) => [o.id, o.name]),
              ]} />
            <${RecField} rec=${rec} name="date" label="Date" type="date" />
          </div>
          <${RecField} rec=${rec} name="dafAccountId" label="Donor-advised fund" id="fund"
            options=${[
              ['', funds.length ? 'Choose…' : 'Add one as an account first'],
              ...funds.map((a) => [a.id, a.name]),
            ]} />
          ${from || kind === 'goods' || kind === 'daf-grant' ? null : html`
            <${RecField} rec=${rec} name="fromAccountId" label="From account" id="from-account"
              hint=${kind === 'cash'
                ? 'Its withdrawal is recorded, categorised Giving. Leave it for one already imported.'
                : ''} options=${[
                ['', kind === 'cash' ? 'Not recorded here' : 'Choose…'],
                ...sources.map((a) => [a.id, a.name]),
              ]} />
          `}
          ${shares
            ? html`
              <${Field} label="From lot" id="lot" error=${rec.error('lotId')}>
                <${Select} value=${lot} onChange=${(/** @type {string} */ x) => {
                  setLot(x);
                  rec.set('lotId', x.split('|')[0] || null);
                }} options=${[
                  ['', lots.length ? 'Choose…' : 'No lots in that account'],
                  ...lots,
                ]} />
                </${Field}>
                <div class="row">
                  <${RecField} rec=${rec} name="quantity" label="Shares" id="quantity"
                    onEdit=${() => {
                      const q = rec.get('quantity');
                      if (price && q != null) {
                        rec.set('amount', dec(price).mul(Dec.of(q)).round(2), 'quantity');
                      }
                    }} />
                  <${RecField} rec=${rec} name="amount" label="Market value" id="amount"
                    hint="On the day given." />
                </div>
                <div class="notice" style=${{ marginBottom: '12px' }}>
                  <${Icon} name="info" />
                  <div>No gain is realized on donated shares. Held over a year, the deduction is
                  the market value; otherwise it is the basis.</div>
                </div>
            `
            : html`
              <${RecField} rec=${rec} name="amount" id="amount"
                label=${kind === 'goods' ? 'Fair market value' : 'Amount'} />
            `}
          <${RecField} rec=${rec} name="description" label="What was given" id="description"
            placeholder="Two bags of clothes" />
          <${RecField} rec=${rec} name="acknowledged" label="Acknowledgement received"
            hint="A written acknowledgement is needed for any single gift of $250 or more." />
        `
        : null}
    </${DraftDialog}>
  `;
}

/**
 * A recorded donation: what changes after the fact, its acknowledgement and a grant paid,
 * edited in a draft and saved with Save.
 * @param {{ close: (v?: any) => void, d: any }} p
 */
function DonationView({ close, d }) {
  useDialogGuide('dialog-donation');
  const f = useDraft((draft) => {
    draft.load(DonationRec, { ...d, receiptIds: [] });
  }, [d.id]);
  const rec = /** @type {DonationRec | undefined} */ (f.draft?.records[0]);
  const [busy, setBusy] = useState(false);
  const [kept, setKept] = useState(0);
  const send = async (/** @type {FileList} */ files) => {
    if (!rec) return;
    setBusy(true);
    try {
      const made = await uploadAll(files);
      rec.set('receiptIds', [...(rec.get('receiptIds') || []), ...made.map((r) => r.id)]);
      if (made.length) rec.set('acknowledged', true, 'receiptIds');
      setKept(kept + made.length);
    } finally {
      setBusy(false);
    }
  };
  return html`
    <${DraftDialog} f=${f} title=${`${d.kindLabel} · ${d.name}`} close=${close}
      what="This donation" hideSave=${!d.access.writable}
      done=${rec?.removed ? 'Donation deleted' : 'Saved'}
      extra=${({ save }) =>
        d.access.writable
          ? html`
            <button type="button" class="btn danger" disabled=${save.busy}
              onClick=${async () => {
                if (!rec || !f.draft) return;
                if (!(await confirmAction({ title: 'Delete this donation?' }))) return;
                f.draft.remove(rec);
                const r = await save.run().catch(() => null);
                if (r?.status !== 'saved') f.draft.unremove(rec);
              }}>Delete</button><span class="spacer"></span>
          `
          : null}>
      <div class="list-item"><span class="grow dim">Date</span>${date(d.date)}</div>
      <div class="list-item"><span class="grow dim">Amount</span><${Amt} v=${d.amount} /></div>
      ${d.symbol
        ? html`
          <div
            class="list-item"><span class="grow dim">Shares</span>${quantity(d.quantity)} ${d
              .symbol} · basis <${Amt} v=${d.basis} /></div>
        `
        : null}
      ${d.description
        ? html`<div class="list-item"><span class="grow dim">Given</span>${d.description}</div>`
        : null}
      <div class="list-item"><span class="grow dim">Deductible</span>${d.deductible
        ? 'yes'
        : 'no'}</div>
      ${rec && d.kind === 'daf-grant' && d.access.writable
        ? html`<${RecField} rec=${rec} name="granted" label="Paid by the fund" />`
        : null}
      ${rec && d.access.writable
        ? html`
          <${RecField} rec=${rec} name="acknowledged" label="Acknowledgement received" />
          <div
            class="toolbar"><label class="btn sm" for="f-ack-files"><${Icon} name="clip" /> ${busy
              ? 'Uploading…'
              : kept
              ? `${kept} acknowledgement${kept === 1 ? '' : 's'} to keep on Save`
              : 'Attach the acknowledgement'}</label><input id="f-ack-files" class="sr-only"
              type="file" accept=${ACCEPT} data-help="acknowledgement" onChange=${(
                /** @type {any} */ ev,
              ) => {
                send(ev.currentTarget.files);
                ev.currentTarget.value = '';
              }} /></div>
        `
        : null}
    </${DraftDialog}>
  `;
}

/** An organisation given to (S7.9.5). */
class OrganisationRec extends Rec {
  /** @override */
  static prefix = 'Orgzn';
  /** @override */
  static fields = FIELDS.OrganisationRecord;
  /** @override */
  static defaults = {
    ein: null,
    deductible: true,
    causes: [],
    pledge: null,
    pledgeEvery: 'month',
    notes: null,
  };
  /** @override */
  static rules = {
    pledgeEvery: { when: (/** @type {OrganisationRec} */ r) => r.get('pledge') != null },
  };
}

/** @param {{ close: (v?: any) => void, o: any }} p */
function OrganisationDialog({ close, o }) {
  useDialogGuide('dialog-organisation');
  const f = useDraft((draft) => {
    if (o) draft.load(OrganisationRec, o);
    else draft.add(OrganisationRec, { name: '' });
  }, [o?.id]);
  const rec = /** @type {OrganisationRec | undefined} */ (f.draft?.records[0]);
  const canWrite = !o || o.access.writable;
  return html`
    <${DraftDialog} f=${f} title=${o ? o.name : 'Add an organisation'} close=${close}
      what="This organisation" done="Saved" hideSave=${!canWrite}>
      ${rec
        ? html`
          <fieldset disabled=${!canWrite} style=${{
            border: 0,
            padding: 0,
            margin: 0,
            minWidth: 0,
          }}>
            <${RecField} rec=${rec} name="name" label="Name"
              placeholder="Greater Chicago Food Depository" />
            <${RecField} rec=${rec} name="ein" label="EIN" hint="Optional: 36-3136294." />
            <${RecField} rec=${rec} name="deductible" label="Deductible"
              hint="A 501(c)(3) charity. Not a political campaign or a person." />
            <${RecField} rec=${rec} name="causes" label="Causes"
              hint="Separated by commas: Hunger, Local." />
            <div class="row">
              <${RecField} rec=${rec} name="pledge" label="Pledge"
                hint="Shown as expected donations." />
              <${RecField} rec=${rec} name="pledgeEvery" label="Every" id="pledge-every"
                options=${[['month', 'Month'], ['year', 'Year']]} />
            </div>
            <${RecField} rec=${rec} name="notes" label="Notes" rows=${2} />
          </fieldset>
        `
        : null}
    </${DraftDialog}>
  `;
}
