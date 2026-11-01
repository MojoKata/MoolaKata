// Taxes (requirements S8, S12.2.10): the tax-book picker, New tax book and Share, then the
// book's Summary, Filings and Documents.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { date, money, thisYear } from '../app/format.js';
import { useTitle } from '../components/frame.js';
import { useDialogGuide, useGuide } from '../components/help.js';
import { Amt } from '../components/amount.js';
import { Empty, Failed, Loading, Tabs } from '../components/bits.js';
import { openDialog } from '../components/dialog.js';
import { Field, Input, Seg, Select, SwitchRow } from '../components/fields.js';
import { Icon } from '../components/icon.js';
import { ShareDialog } from '../components/share.js';
import { toast } from '../components/toast.js';
import { ACCEPT, uploadAll } from '../components/receipt.js';
import { book as bookPref } from '../store/prefs.js';
import { Panel, PANEL_TABS, SummaryFigures } from '../components/taxpanels.js';
import { Dec } from '../app/dec.js';
import { canAdd, Record as Rec, TYPES } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { DraftDialog, RecField, saveNow, saveOne, useDraft } from '../components/draft-form.js';
import { confirmAction } from '../components/confirm.js';

export const TABS = /** @type {[string, string][]} */ ([
  ['summary', 'Summary'],
  ['filings', 'Filings'],
  ...PANEL_TABS.filter(([k]) => k !== 'issues'),
  ['documents', 'Documents'],
  ['issues', 'Issues'],
]);
const PROGRESS = /** @type {[string, string][]} */ ([
  ['not started', 'Not started'],
  ['in progress', 'In progress'],
  ['filed', 'Filed'],
  ['accepted', 'Accepted'],
  ['rejected', 'Rejected'],
]);
const TONE = /** @type {Record<string, string>} */ ({
  'not started': '',
  'in progress': 'info',
  filed: 'info',
  accepted: 'ok',
  rejected: 'bad',
});
const CARRIED = /** @type {[string, string][]} */ ([
  ['agi', 'Adjusted gross income'],
  ['totalTax', 'Total tax'],
  ['overpaymentApplied', 'Overpayment applied'],
  ['capitalLossShort', 'Capital-loss carryover, short term'],
  ['capitalLossLong', 'Capital-loss carryover, long term'],
  ['basis8606', 'Form 8606 basis'],
  ['charitableCarryover', 'Charitable carryover'],
]);
const CHILD_TYPES = [
  'checking',
  'savings',
  'money-market',
  'cd',
  'brokerage',
  'crypto-exchange',
  'crypto-wallet',
];

/** @param {{ tab?: string }} p */
export default function Taxes({ tab }) {
  const current = TABS.some(([k]) => k === tab) ? /** @type {string} */ (tab) : 'summary';
  useTitle('Taxes');
  useGuide('taxes-' + current);
  const list = useApi('/tax-books', {}, ['share']);
  const v = /** @type {any} */ (list.data);
  const rows = /** @type {any[]} */ (v?.books);
  if (list.error) return html`<${Failed} error=${list.error} />`;
  if (!rows) return html`<${Loading} />`;
  const create = () =>
    openDialog(NewBook, { rows }).then((b) => {
      if (b) {
        bookPref.value = b.id;
        list.reload();
      }
    });
  // Books the user is named in and hasn't accepted come apart from those they hold (S8.14.1).
  const pending = /** @type {any[]} */ (v.waiting);
  const held = rows;
  const chosen = held.find((r) => r.id === bookPref.value) || held[0];
  return html`
    ${pending.map((r) =>
      html`<div class="notice mb"><${Icon} name="info" /><div>You're named as a filer in
        the ${r.label} tax book. Once you accept, it counts your accounts.</div><button
        class="btn sm primary" onClick=${() =>
        api.post(`/tax-books/${r.id}/accept`).then(() => {
          toast('Accepted');
          bookPref.value = r.id;
          list.reload();
        })}>Accept</button></div>`
    )}
    <div class="toolbar">
      ${held.length
        ? html`
          <${Field} label="Tax book" id="tax-book">
            <${Select} value=${chosen?.id}
              onChange=${(/** @type {string} */ v) => (bookPref.value = v)}
              options=${held.map((r) => [r.id, r.label])} />
            </${Field}>
        `
        : null}
      <span class="spacer"></span>
      <button class="btn" onClick=${create}><${Icon} name="plus" /> New tax book</button>
      ${chosen && chosen.access.shareable
        ? html`<button class="btn" onClick=${() =>
          openDialog(ShareDialog, {
            kind: 'tax-book',
            id: chosen.id,
            name: `Tax book ${chosen.label}`,
          })}><${Icon} name="share" /> Share</button>`
        : null}
    </div>
    ${chosen
      ? html`<${Book} key=${chosen.id} id=${chosen.id} tab=${current} />`
      : html`<${Empty}>No tax book yet. A tax book is one year's tax record, for you or for you
        and your spouse filing jointly.<div class="mt"><button class="btn primary"
          onClick=${create}><${Icon} name="plus" /> New tax book</button></div></${Empty}>`}
  `;
}

/** @param {{ id: string, tab: string }} p */
function Book({ id, tab }) {
  const res = useApi(`/tax-books/${id}`, {}, ['import', 'receipt']);
  const b = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!b) return html`<${Loading} lines=${6} />`;
  const done = (/** @type {any} */ out) => {
    if (out) res.reload();
  };
  return html`
    <${Tabs} tabs=${TABS} current=${tab} base="/ui/taxes" />
    ${tab === 'summary' ? html`<${Summary} b=${b} done=${done} />` : null}
    ${tab === 'filings' ? html`<${Filings} b=${b} done=${done} />` : null}
    ${tab === 'documents' ? html`<${Documents} b=${b} done=${done} />` : null}
    ${PANEL_TABS.some(([k]) => k === tab) ? html`<${Panel} b=${b} tab=${tab} />` : null}
  `;
}

/** An account a tax book adds or leaves out (S8.14.2). */
class BookAccountRec extends Rec {
  /** @override */
  static prefix = 'TxBkA';
  /** @override */
  static fields = FIELDS.BookAccountRecord;
}

/** @param {{ b: any, done: (out: any) => void }} p */
function Summary({ b, done }) {
  // An account added or left out is a record of its own (S8.14.2); Count it again takes it
  // back to what the filers' accounts say.
  const count = useSubmit(async (/** @type {any} */ a, /** @type {boolean | null} */ on) => {
    const row = a.rowId
      ? { id: a.rowId, version: a.rowVersion, bookId: b.id, accountId: a.id }
      : null;
    const out = on === null && row
      ? await saveNow((d) => d.remove(d.load(BookAccountRec, row)))
      : await saveOne(BookAccountRec, row, { bookId: b.id, accountId: a.id, counted: !!on });
    done(out[0]?.record || true);
  });
  const [adding, setAdding] = useState('');
  const missing = b.expected.filter((/** @type {any} */ e) => !e.document).length;
  return html`
    <${SummaryFigures} b=${b} />
    <div class="grid g4 mt">
      <div class="card kpi">
        <div class="label">Filers</div>
        <div style=${{ fontSize: '16px', fontWeight: 600, marginTop: '6px' }}>${b.filers.map((
          /** @type {any} */ f,
        ) => f.name).join(' & ')}</div>
        <div class="delta dim">${b.filers.some((
            /** @type {any} */ f,
          ) => !f.accepted
          )
          ? 'waiting for a filer to accept'
          : b.filers.length > 1
          ? 'filing jointly'
          : 'one filer'}</div>
      </div>
      <div class="card kpi">
        <div class="label">Accounts counted</div>
        <div class="value">${b
          .accounts.length}</div>
        <div class="delta dim">${b.leftOut.length
          ? `${b.leftOut.length} left out`
          : 'all the filers’ own'}</div>
      </div>
      <div class="card kpi">
        <div class="label">Filings</div>
        <div class="value">${b.filings
          .length}</div>
        <div class="delta dim">${b.filings.filter((/** @type {any} */ f) => f.overdue).length
          ? html`<span class="down">past due</span>`
          : `federal due ${date(b.federalDue)}`}</div>
      </div>
      <div class="card kpi">
        <div class="label">Documents</div>
        <div class="value">${b.expected
          .length - missing} of ${b.expected.length}</div>
        <div class="delta dim">${missing ? `${missing} still to come` : 'all received'}</div>
      </div>
    </div>
    <div class="grid g2 mt">
      <div class="card"><h3 data-help="accounts-counted">Accounts counted</h3>${b.accounts.map((
        /** @type {any} */ a,
      ) =>
        html`
          <div
            class="list-item"><div class="grow">${a.name}<div class="small dim">${a
              .ownerName}</div></div>${b.access.configurable
              ? html`<button class="btn sm" onClick=${() =>
                count.run(a, false).catch(() => {})}>Leave out</button>`
              : null}</div>
        `
      )}
        ${b.leftOut.length
          ? html`
            <h4 style=${{ margin: '12px 0 6px' }}>Left out</h4>${b.leftOut.map((
              /** @type {any} */ a,
            ) =>
              html`<div class="list-item"><span class="grow dim">${a.name}</span>${
                b.access.writable
                  ? html`<button class="btn sm" onClick=${() =>
                    count.run(a, null).catch(() => {})}>Count it</button>`
                  : null
              }</div>`
            )}<p
              class="small dim">The panels leave these out, and say so.</p>
          `
          : null}
        ${canAdd('TxBkA', b) && b.addable.length
          ? html`
            <div class="row mt">
              <${Field} label="Add an account" id="add-account"
                hint="One you can see, such as a custodial account in a child's name."><${Select}
                        value=${adding} onChange=${setAdding} options=${[
                          ['', 'Choose…'],
                          ...b.addable.map((
                            /** @type {any} */ a,
                          ) => [a.id, `${a.name} · ${a.ownerName}`]),
                        ]} /></${Field}><button class="btn sm" style=${{
                          alignSelf: 'end',
                        }} disabled=${!adding}
                        onClick=${() =>
                          count.run(b.addable.find((/** @type {any} */ x) => x.id === adding), true)
                            .then(() => setAdding('')).catch(
                              () => {},
                            )}>Add</button></div>
          `
          : null}
      </div>
      <div class="card"><h3 data-help="from-last-year">From last year</h3>${b.lastYear.length
        ? b.lastYear.map((/** @type {any} */ l) =>
          html`<h4 style=${{ margin: '8px 0 4px' }}>${l.filing}</h4>${
            CARRIED.filter(([k]) => l.figures[k] != null).map(([k, label]) =>
              html`<div class="list-item"><span class="grow dim">${label}</span><${Amt}
              v=${l.figures[k]} /></div>`
            )
          }`
        )
        : html`<p class="small dim">Nothing carried forward: last year's filings, once typed in,
          show here what this year needs (AGI to sign the e-filed return, carryovers, the 8606
          basis).</p>`}</div>
    </div>
    <${Dependents} b=${b} done=${done} />
    <p class="small dim mt">MoolaKata gathers what a preparer or tax software needs. It never
      computes the tax, chooses a filing status, or files.</p>
  `;
}

/** How old a dependent is on Dec 31, and what that makes them for the credits. */
const ageLine = (/** @type {any} */ d, /** @type {number} */ year) => {
  if (d.age == null) return 'Age unknown: no birth year';
  const marks = [d.under13 && 'under 13', d.under17 && 'under 17'].filter(Boolean);
  return `Age ${d.age} on Dec 31, ${year}${marks.length ? ': ' + marks.join(' and ') : ''}`;
};

/** @param {{ b: any, done: (out: any) => void }} p */
function Dependents({ b, done }) {
  const open = (/** @type {any} */ d) => openDialog(DependentDialog, { b, d }).then(done);
  return html`
    <div
      class="card mt"><h3 data-help="dependents">Dependents<span class="spacer"></span>${b
          .access.writable
        ? html`<button class="btn sm" onClick=${() => open(null)}><${Icon} name="plus" /> Add
          dependent</button>`
        : null}</h3>
      ${b.dependents.length
        ? b.dependents.map((/** @type {any} */ d) =>
          html`
            <div class=${'list-item' + (b.access.writable ? ' click' : '')}
              onClick=${b.access.writable ? () => open(d) : null}><div class="grow"><b>${d
                .name}</b><div class="small dim">${[
                d.relation && d.relation[0].toUpperCase() + d.relation.slice(1),
                d.claimedAs,
                `${d.months} month${d.months === 1 ? '' : 's'}`,
                d.student && 'student',
              ].filter(Boolean).join(' · ')}${d.agesOut.length
                ? html`<br />${d.agesOut.join('; ')}`
                : null}</div></div><span class="small">${ageLine(d, b.year)}</span>${d
                  .claimedElsewhere
                ? html`
                  <span class="pill warn" title="Claimed on another tax book for this year"
                  >also claimed elsewhere</span>
                `
                : null}</div>
          `
        )
        : html`<p class="small dim">No one claimed this year. Add the people you claim: their
          ages feed the credits panel, and a student's 1098-T is expected.</p>`}
      ${b.form8615.map((/** @type {any} */ f) =>
        html`
          <div class="notice mt">
            <${Icon} name="alert" />
            <div>${f.name}'s ${f.accounts.join(
              ' and ',
            )} earned ${money(f.unearned)} of unearned income this year, above the ${money(
              f.threshold,
            )} threshold: Form 8615 (the kiddie tax) may apply.</div>
          </div>
        `
      )}
      ${b.claimedElsewhere.map((/** @type {string} */ n) =>
        html`
          <div class="notice mt">
            <${Icon} name="info" />
            <div>${n} is claimed as a dependent on
                    another ${b.year} tax book.</div>
          </div>
        `
      )}
    </div>
  `;
}

/** A dependent of a book (S8.14.5), with the accounts in their name it counts. */
class DependentRec extends Rec {
  /** @override */
  static prefix = 'TxDep';
  /** @override */
  static fields = FIELDS.DependentRecord;
  /** @override */
  static defaults = { claimedAs: 'qualifying child', months: 12, student: false, accountIds: [] };
}

/** @param {{ close: (v?: any) => void, b: any, d: any }} p */
function DependentDialog({ close, b, d }) {
  useDialogGuide('dialog-dependent');
  const cands = useList(`/tax-books/${b.id}/dependent-candidates`);
  const list = /** @type {any[] | null} */ (cands.data);
  const f = useDraft((draft) => {
    if (d) draft.load(DependentRec, { ...d, bookId: b.id });
    else draft.add(DependentRec, { bookId: b.id, personId: '' });
  }, [d?.id]);
  const rec = /** @type {DependentRec | undefined} */ (f.draft?.records[0]);
  // How they are claimed follows the family tree's suggestion until it is chosen.
  const [picked, setPicked] = useState(!!d);
  const taken = new Set(b.dependents.map((/** @type {any} */ x) => x.personId));
  const choices = (list || []).filter((c) => !taken.has(c.personId) || c.personId === d?.personId);
  /** @param {string} who @param {boolean} student */
  const suggest = (who, student) => {
    const c = choices.find((x) => x.personId === who);
    if (!rec || picked || !c) return;
    rec.set('claimedAs', (student ? c.suggestIfStudent : c.suggest) || 'qualifying child', who);
  };
  const ids = /** @type {string[]} */ (rec?.get('accountIds') || []);
  // Accounts a child's money is kept in: banking, brokerage and crypto, not retirement or loans.
  const theirs = b.accounts.filter((/** @type {any} */ a) =>
    CHILD_TYPES.includes(a.type) || ids.includes(a.id)
  );
  const toggle = (/** @type {string} */ id) => (/** @type {boolean} */ on) =>
    rec?.set('accountIds', on ? [...ids, id] : ids.filter((x) => x !== id));
  return html`
    <${DraftDialog} f=${f} close=${close} what="This dependent" title=${d
      ? d.name
      : 'Add a dependent'}
      label=${d ? 'Save' : 'Add'} done=${rec?.removed
        ? 'Dependent removed'
        : d
        ? 'Dependent saved'
        : 'Dependent added'} disabled=${!rec?.get('personId')}
      extra=${({ save }) =>
        d
          ? html`
            <button type="button" class="btn danger" disabled=${save.busy}
              onClick=${async () => {
                if (!rec || !f.draft) return;
                const sure = await confirmAction({
                  title: 'Remove this dependent?',
                  yes: 'Yes, remove',
                });
                if (!sure) return;
                f.draft.remove(rec);
                const r = await save.run().catch(() => null);
                if (r?.status !== 'saved') f.draft.unremove(rec);
              }}>Remove</button><span class="spacer"></span>
          `
          : null}>
      ${rec
        ? html`
          <div class="row">
            <${Field} label="Person" id="person" error=${rec.error('personId')}
              hint="From the household's people. Add someone new on the Gifts screen.">
              <${Select} value=${rec.get('personId') || ''} onChange=${(
                /** @type {string} */ x,
              ) => {
                rec.input('personId', x);
                suggest(x, rec.get('student'));
              }} options=${[
                ['', list ? 'Choose…' : 'Loading…'],
                ...choices.map((c) => [
                  c.personId,
                  c.name + (c.relation ? ` · ${c.relation}` : ''),
                ]),
              ]} />
              </${Field}>
              <${Field} label="Claimed as" id="claimed-as" error=${rec.error('claimedAs')}
                hint="Suggested from the family tree. As you file it.">
              <${Select} value=${rec.get('claimedAs')} onChange=${(/** @type {string} */ x) => {
                setPicked(true);
                rec.input('claimedAs', x);
              }} options=${[
                ['qualifying child', 'Qualifying child'],
                ['qualifying relative', 'Qualifying relative'],
              ]} />
            </${Field}>
          </div>
          <div class="row">
            <${RecField} rec=${rec} name="months" label="Months lived with you" id="months" />
            <${SwitchRow} label="Full-time student" hint="This year, for at least five months."
              on=${rec.get('student')} onChange=${(/** @type {boolean} */ on) => {
                rec.set('student', on);
                suggest(rec.get('personId'), on);
              }} />
          </div>
          ${theirs.length
            ? html`<div class="field" data-help="accounts-in-their-name" id="x-accounts"><label
                >Accounts in their name</label>${
              theirs.map((/** @type {any} */ a) =>
                html`
                  <${SwitchRow} label=${a.name} hint=${a.ownerName}
                    on=${ids.includes(a.id)} onChange=${toggle(a.id)} />
                `
              )
            }<div class="hint">Such as a custodial account: its unearned income is checked
                  against the Form 8615 threshold.</div></div>`
            : null}
          <p class="small dim">Each dependent's age on Dec 31 shows in the panels: under 17, under
            13, and who ages out this year. MoolaKata doesn't decide who qualifies.</p>
        `
        : null}
    </${DraftDialog}>
  `;
}

/** @param {{ b: any, done: (out: any) => void }} p */
function Filings({ b, done }) {
  const open = (/** @type {any} */ f) => openDialog(FilingDialog, { b, f }).then(done);
  return html`
    <div class="toolbar"><span class="small dim">One per return. An amended return is a filing
      of its own.</span><span class="spacer"></span>${canAdd('Filng', b)
        ? html`<button class="btn sm" onClick=${() => open(null)}><${Icon} name="plus" /> Add a
        filing</button>`
        : null}</div>
    ${b.filings.length
      ? b.filings.map((/** @type {any} */ f) =>
        html`
          <div
            class="card mt"><h3>${f.label}<span class=${'pill ' + (TONE[f.progress] ||
              '')}>${PROGRESS.find(([k]) => k === f.progress)?.[1]}</span>${f.overdue
              ? html`<span class="pill warn">past its due date</span>`
              : null}<span class="spacer"></span><button class="btn sm" onClick=${() =>
              open(f)}>${b.access.writable ? 'Edit' : 'Open'}</button></h3>
                    <div class="grid g4">
                      <div><div class="small dim">Due</div>${f.extendedDue
                        ? html`${date(f.extendedDue)} <span class="small dim">extended</span>`
                        : f.dueDate
                        ? date(f.dueDate)
                        : '—'}</div>
                      <div><div class="small dim">Filed</div>${f.filedOn
                        ? date(f.filedOn)
                        : '—'}${f.sentBy
                        ? html`
                          <span class="small dim">· ${f.sentBy}</span>
                        `
                        : null}</div>
                      <div><div class="small dim">Result</div>${f.resultKind === 'refund'
                        ? html`Refund <${Amt} v=${f.resultAmount} />`
                        : f.resultKind === 'owed'
                        ? html`Owed <${Amt} v=${f.resultAmount} />`
                        : f.resultKind === 'none'
                        ? 'Nothing due'
                        : '—'}${f.resultPaid
                        ? html`<div class="small dim">${f.resultPaid}</div>`
                        : null}</div>
                      <div><div class="small dim">Documents</div>${f.documents.length || '—'}</div>
                    </div>
                    ${f.payments.length
                      ? html`<div class="small dim mt">Estimated payments: ${
                        f.payments.map((
                          /** @type {any} */ p,
                        ) => `Q${p.quarter} ${money(p.amount, { cents: false })}`).join(
                          ' · ',
                        )
                      }</div>`
                      : null}
                  </div>
        `
      )
      : html`<${Empty}>No filings yet. Add the federal return, and any state or local ones.</${Empty}>`}
  `;
}

/** @param {{ b: any, done: (out: any) => void }} p */
function Documents({ b, done }) {
  const add = (/** @type {any} */ start) => openDialog(DocumentDialog, { b, start }).then(done);
  // A document kept opens to change or remove it (CR3-36).
  const open = (/** @type {any} */ doc) =>
    b.access.writable && openDialog(DocumentDialog, { b, doc }).then(done);
  const filed = b.filings.flatMap((/** @type {any} */ f) =>
    f.documents.map((/** @type {any} */ d) => ({ ...d, filing: f.label }))
  );
  return html`
    <div
      class="toolbar"><h3 style=${{ margin: 0 }}>Received</h3><span class="spacer"></span>${b
          .access.writable
        ? html`<button class="btn sm" onClick=${() => add(null)}><${Icon} name="plus" /> Add a
        document</button>`
        : null}</div>
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table class="t">
          <caption class="sr-only">Documents received and expected</caption>
          <thead>
            <tr>
              <th>Document</th>
              <th>From</th>
              <th>Why expected</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
        ${b.expected.map((/** @type {any} */ e) =>
          html`
            <tr class=${e.document && b.access.writable ? 'click' : ''} onClick=${() =>
              e.document && open(e.document)}>
              <td>${e.form}</td>
              <td class="dim">${e.issuer || '—'}</td>
              <td class="small dim">${e
                .why}</td>
              <td>${e.document
                ? html`<span class="pill ok"><${Icon} name="check" /> received</span>${
                  e.document
                      .fileName
                    ? html`
                      <span class="small dim"><${Icon} name="clip" /> ${e.document.fileName}</span>
                    `
                    : null
                }`
                : b.access.writable
                ? html`<button class="btn sm" onClick=${(/** @type {Event} */ ev) => {
                  ev.stopPropagation();
                  add({
                    form: e.form,
                    issuer: e.issuer,
                    accountId: e.accountId,
                  });
                }}><${Icon} name="upload" /> Attach</button>`
                : html`<span class="pill warn">missing</span>`}</td>
            </tr>
          `
        )}
        ${b.received.map((/** @type {any} */ d) =>
          html`
            <tr class=${b.access.writable ? 'click' : ''} onClick=${() => open(d)}>
              <td>${d.form}</td>
              <td class="dim">${d.issuer || '—'}</td>
              <td
                class="small dim">added</td>
              <td><span class="pill ok"><${Icon} name="check" />
                        received</span>${d.fileName
                          ? html`
                            <span class="small dim"><${Icon} name="clip" /> ${d.fileName}</span>
                          `
                          : null}</td>
            </tr>
          `
        )}
      </tbody>
        </table>
      </div>
    </div>
    <div
      class="toolbar mt"><h3 style=${{
        margin: 0,
      }}>Filed</h3><span class="spacer"></span>${canAdd('TxDoc', b) && b.filings.length
        ? html`<button class="btn sm" onClick=${() =>
          add({
            direction: 'filed',
            filingId: b.filings[0].id,
          })}><${Icon} name="plus" /> Add a filed
        document</button>`
        : null}</div>
    ${filed.length
      ? html`<div class="card" style=${{ padding: '4px 8px' }}>${
        filed.map((/** @type {any} */ d) =>
          html`
            <div class=${'list-item' + (b.access.writable ? ' click' : '')}
              onClick=${() => open(d)}><div class="grow">${d.form}<div class="small dim">${d
                .filing}${d.issuer ? ` · ${d.issuer}` : ''}${d.notes
                ? ` · ${d.notes}`
                : ''}</div></div>${d
                  .fileName
                ? html`<span class="small dim"><${Icon} name="clip" /> ${d.fileName}</span>`
                : null}</div>
          `
        )
      }</div>`
      : html`<p class="small dim">The return as filed, the e-file acknowledgement, and what the
        tax authority sends. Next year's preparation often needs them.</p>`}
  `;
}

/** A tax book (S8.14), as New tax book's draft makes it. */
class BookRec extends Rec {
  /** @override */
  static prefix = 'TaxBk';
  /** @override */
  static fields = FIELDS.BookRecord;
}

/** @param {{ close: (v?: any) => void, rows: any[] }} p */
function NewBook({ close, rows }) {
  useDialogGuide('dialog-tax-book');
  const me = useApi('/profile');
  const p = /** @type {any} */ (me.data);
  const year = thisYear();
  const f = useDraft(async (draft) => {
    const who = await api.get('/profile');
    draft.add(BookRec, {
      year: year - 1,
      filers: [who.id],
      fromLastYear: true,
      bitcoinFees: 'sale',
    });
  }, []);
  const rec = /** @type {BookRec | undefined} */ (f.draft?.records[0]);
  const spouse = p?.spouse || null;
  const joint = !!spouse && (rec?.get('filers') || []).includes(spouse.id);
  const has = rows.some((r) => r.year === (rec?.get('year') ?? 0) - 1);
  return html`
    <${DraftDialog} f=${f} title="New tax book" close=${close} what="This tax book"
      label="Create" saved=${(/** @type {any} */ o) => {
        const out = o.saved[0].record;
        toast(
          out.dependentsLeftOut.length
            ? `Tax book made. Left out, past a qualifying child's age: ${
              out.dependentsLeftOut.join(', ')
            }`
            : 'Tax book made',
        );
        close(out);
      }}>
      ${rec && p
        ? html`
          <${RecField} rec=${rec} name="year" label="Year"
            options=${[year, year - 1, year - 2].map((y) => [String(y), String(y)])} />
          <${SwitchRow} label="Filing jointly" hint=${spouse
            ? `With ${spouse.displayName}, who is asked to accept before their accounts count.`
            : 'Add your spouse among your relationships in Profile to file jointly.'}
            on=${joint} disabled=${!spouse} onChange=${(/** @type {boolean} */ on) =>
              rec.set('filers', on ? [p.id, spouse.id] : [p.id])} />
          <${RecField} rec=${rec} name="fromLastYear" label="Start from last year" hint=${has
            ? "Copies last year's accounts left out or added and its dependents; its received documents become this year's expected ones."
            : 'No book for the year before.'} />
          <${RecField} rec=${rec} name="bitcoinFees" label="Bitcoin network fees"
            id="bitcoin-fees"
            hint="On transfers between your own accounts. A sale of the fee's sats is the common reading."
            options=${[
              ['sale', 'A sale, in Form 8949'],
              ['not-taxed', 'Not taxed, as my preparer reads them'],
            ]} />
        `
        : null}
    </${DraftDialog}>
  `;
}

/** A filing (S8.15), as its dialog's draft edits it. */
class FilingRec extends Rec {
  /** @override */
  static prefix = 'Filng';
  /** @override */
  static fields = FIELDS.FilingRecord;
  /** @override */
  static defaults = {
    jurisdiction: 'federal',
    place: null,
    form: 'Form 1040',
    amendsId: null,
    filingStatus: null,
    preparedBy: null,
    sentBy: 'e-file',
    progress: 'not started',
    dueDate: null,
    extensionFiledOn: null,
    extendedDue: null,
    filedOn: null,
    confirmation: null,
    resultKind: null,
    resultAmount: null,
    resultTransactionId: null,
    carried: {},
  };
  /** @override */
  static rules = {
    // A federal return has no place of its own.
    place: { when: (/** @type {FilingRec} */ r) => r.get('jurisdiction') !== 'federal' },
  };
}

/** An estimated payment of a filing, matched to its transaction. */
class PaymentRec extends Rec {
  /** @override */
  static prefix = 'EstPy';
  /** @override */
  static fields = FIELDS.PaymentRecord;
  /** @override */
  static defaults = { dueDate: null, amount: null, paidOn: null, transactionId: null };
  /** @override */
  static ownedBy = ['filingId'];
}

/** A carried figure typed: an amount in cents, or nothing. @param {string} t */
const carriedAmount = (t) => {
  if (!t.trim()) return { value: null };
  const r = TYPES.money.parse(t, { type: 'money' });
  return 'error' in r ? r : { value: Dec.of(r.value).round(2) };
};

/** @param {{ close: (v?: any) => void, b: any, f: any }} p */
function FilingDialog({ close, b, f: filing }) {
  useDialogGuide('dialog-filing');
  const meta = useApi('/tax-forms');
  const txns = useApi('/transactions', { limit: 200 });
  const f = useDraft(async (draft) => {
    if (!filing) {
      draft.add(FilingRec, {
        bookId: b.id,
        filingStatus: b.filers.length > 1 ? 'Married filing jointly' : null,
      });
      return;
    }
    const book = await api.get(`/tax-books/${b.id}`);
    const x = book.filings.find((/** @type {any} */ y) => y.id === filing.id);
    draft.load(FilingRec, { ...x, bookId: b.id });
    for (const p of x.payments) draft.load(PaymentRec, { ...p, filingId: x.id });
  }, [filing?.id]);
  const draft = f.draft;
  const rec = /** @type {FilingRec | undefined} */ (
    draft?.records.find((r) => r instanceof FilingRec)
  );
  const payments = /** @type {PaymentRec[]} */ (
    (draft?.records || []).filter((r) => r instanceof PaymentRec && !r.removed)
  );
  const can = b.access.writable;
  const statuses = /** @type {any} */ (meta.data)?.statuses || [];
  const items = /** @type {any} */ (txns.data)?.items || [];
  const where = rec?.get('jurisdiction');
  const carried = rec?.get('carried') || {};
  return html`
    <${DraftDialog} f=${f} wide close=${close} what="This filing"
      title=${filing ? `${filing.label} · ${b.year}` : 'Add a filing'}
      done=${rec?.removed ? 'Filing deleted' : 'Filing saved'} hideSave=${!can}
      extra=${({ save }) =>
        can && filing
          ? html`
            <button type="button" class="btn danger" disabled=${save.busy}
              onClick=${async () => {
                if (!rec || !draft) return;
                if (!(await confirmAction({ title: 'Delete this filing?' }))) return;
                draft.remove(rec);
                const r = await save.run().catch(() => null);
                if (r?.status !== 'asks' && r?.status !== 'saved') draft.unremove(rec);
              }}>Delete</button><span class="spacer"></span>
          `
          : null}>
      ${rec
        ? html`
          <fieldset disabled=${!can} style=${{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
            <div class="row">
              <${RecField} rec=${rec} name="jurisdiction" label="Jurisdiction" options=${[
                ['federal', 'Federal'],
                ['state', 'A state'],
                ['local', 'A locality'],
              ]} />
              <${RecField} rec=${rec} name="place" id="place"
                label=${where === 'state' ? 'State' : 'Locality'}
                placeholder=${where === 'state' ? 'Utah' : 'New York City'} />
              <${RecField} rec=${rec} name="form" label="Form" placeholder="Form 1040, TC-40…" />
              <${RecField} rec=${rec} name="amendsId" label="Amends" id="amends" options=${[
                ['', 'Nothing: an original return'],
                ...b.filings.filter((/** @type {any} */ x) => x.id !== filing?.id).map((
                  /** @type {any} */ x,
                ) => [x.id, x.label]),
              ]} />
            </div>
            <div class="row">
              <${RecField} rec=${rec} name="filingStatus" label="Filing status"
                id="filing-status" hint="As filed. MoolaKata never chooses it." options=${[
                  ['', 'Not chosen yet'],
                  ...statuses.map((/** @type {string} */ x) => [x, x]),
                ]} />
              <${RecField} rec=${rec} name="preparedBy" label="Prepared by" id="prepared-by"
                placeholder="yourself, software, a preparer" />
              <${RecField} rec=${rec} name="sentBy" label="Sent by" id="sent-by" options=${[
                ['e-file', 'E-file'],
                ['paper', 'Paper'],
              ]} />
            </div>
            <div class="field" data-help="progress" id="x-progress"><label>Progress</label>
              <${Seg} label="Progress" value=${rec.get('progress')} onChange=${(
                /** @type {string} */ v,
              ) => rec.set('progress', v)} options=${PROGRESS} />
              ${rec.error('progress')
                ? html`<div class="err" role="alert">${rec.error('progress')}</div>`
                : null}</div>
            <div class="row">
              <${RecField} rec=${rec} name="dueDate" label="Due date" id="due-date" type="date"
                hint=${where === 'federal' ? 'Blank: from the tax tables.' : ''} />
              <${RecField} rec=${rec} name="extensionFiledOn" label="Extension filed"
                id="extension-filed-on" type="date" />
              <${RecField} rec=${rec} name="extendedDue" label="Extended to" id="extended-due"
                type="date" />
              <${RecField} rec=${rec} name="filedOn" label="Date filed" id="filed-on"
                type="date" />
            </div>
            <${RecField} rec=${rec} name="confirmation" label="Confirmation number"
              id="confirmation" placeholder="submission ID or mailing receipt" />
            <div class="row">
              <${RecField} rec=${rec} name="resultKind" label="Result" id="result-kind" options=${[
                ['', 'Not known yet'],
                ['refund', 'Refund'],
                ['owed', 'Amount owed'],
                ['none', 'Nothing due'],
              ]} />
              <${RecField} rec=${rec} name="resultAmount" label="Amount" id="result-amount" />
              <${RecField} rec=${rec} name="resultTransactionId" label="Paid or received in"
                id="result-transaction" hint="Match the transaction." options=${[
                  ['', 'Not yet'],
                  ...items.map((/** @type {any} */ t) => [
                    t.id,
                    `${t.accountName || ''} · ${date(t.date)} · ${t.payee || ''} ${t.amount}`,
                  ]),
                ]} />
            </div>
            <div class="toolbar"><b class="small" data-help="estimated-payments">Estimated
                payments</b><span class="spacer"></span><button type="button" class="btn sm"
                onClick=${() =>
                  draft?.add(PaymentRec, {
                    filingId: rec.id,
                    quarter: Math.min(4, payments.length + 1),
                  })}><${Icon} name="plus" /> Add a payment</button></div>
            ${payments.map((p, i) =>
              html`
                <div class="row" key=${p.key}>
                  <${Field} label="Quarter" help="estimated-payments" id=${'quarter-' + i}>
                    <${RecField} rec=${p} name="quarter" bare label="Quarter"
                      options=${['1', '2', '3', '4']} />
                    </${Field}>
                    <${Field} label="Due" help="estimated-payments" id=${'pay-due-' + i}>
                      <${RecField} rec=${p} name="dueDate" bare label="Due" type="date" />
                      </${Field}>
                      <${Field} label="Amount" help="estimated-payments" id=${'pay-amount-' + i}
                        error=${p.error('amount')}>
                        <${RecField} rec=${p} name="amount" bare label="Amount" />
                        </${Field}>
                        <${Field} label="Paid on" help="estimated-payments" id=${'pay-on-' + i}>
                          <${RecField} rec=${p} name="paidOn" bare label="Paid on" type="date" />
                          </${Field}>
                          <button type="button" class="icon-btn" aria-label="Remove the payment"
                            onClick=${() => draft?.remove(p)}><${Icon} name="x" /></button>
                          </div>
              `
            )}
            <h4 style=${{ margin: '10px 0 2px' }} data-help="carried-forward">Carried forward to
              next year</h4>
            <p class="small dim" style=${{ marginTop: 0 }}>Typed from the return as filed. Next
              year's tax book shows them under <b>From last year</b>.</p>
            <div class="row" style=${{ flexWrap: 'wrap' }}>${CARRIED.map(([k, label]) =>
              html`
                <${Field} label=${label} help="carried-forward" id=${'carried-' + k}
                  error=${rec.error('carried-' + k)}>
                  <${Input} value=${rec.typed('carried-' + k) ??
                    (carried[k] == null ? '' : String(carried[k]))} inputmode="decimal"
                    onInput=${(/** @type {string} */ x) =>
                      rec.inputAs('carried-' + k, x, (t) => {
                        const r = carriedAmount(t);
                        return 'error' in r
                          ? r
                          : { value: { carried: { ...rec.get('carried'), [k]: r.value } } };
                      })} />
                  </${Field}>
              `
            )}</div>
          </fieldset>
        `
        : null}
    </${DraftDialog}>
  `;
}

/** A tax document (S8.16), received or filed, with its file. */
class DocumentRec extends Rec {
  /** @override */
  static prefix = 'TxDoc';
  /** @override */
  static fields = FIELDS.DocumentRecord;
  /** @override */
  static defaults = {
    direction: 'received',
    issuer: null,
    accountId: null,
    filingId: null,
    receiptId: null,
    notes: null,
  };
  /** @override */
  static rules = {
    // A filed document belongs to a filing; a received one may report on an account.
    filingId: { when: (/** @type {DocumentRec} */ r) => r.get('direction') === 'filed' },
    accountId: { when: (/** @type {DocumentRec} */ r) => r.get('direction') !== 'filed' },
  };
}

/**
 * A tax document kept, or one to keep: `doc` opens a kept one to change its form, issuer,
 * account, notes or file, or to remove it (CR3-36); `start` fills a new one.
 * @param {{ close: (v?: any) => void, b: any, start?: any, doc?: any }} p
 */
function DocumentDialog({ close, b, start, doc }) {
  useDialogGuide('dialog-tax-document');
  const meta = useApi('/tax-forms');
  const forms = /** @type {any} */ (meta.data) || { received: [], filed: [] };
  const f = useDraft((draft) => {
    if (doc) {
      draft.load(DocumentRec, { ...doc, bookId: b.id });
      return;
    }
    const filed = start?.direction === 'filed';
    draft.add(DocumentRec, {
      bookId: b.id,
      direction: start?.direction || 'received',
      form: start?.form || (filed ? 'Return as filed' : 'W-2'),
      issuer: start?.issuer || null,
      accountId: start?.accountId || null,
      filingId: start?.filingId || null,
    });
  }, [doc?.id]);
  const rec = /** @type {DocumentRec | undefined} */ (f.draft?.records[0]);
  const [file, setFile] = useState(
    /** @type {any} */ (doc?.fileName ? { name: doc.fileName } : null),
  );
  const filed = rec?.get('direction') === 'filed';
  return html`
    <${DraftDialog} f=${f} close=${close} what="This document"
      title=${doc ? doc.form : filed ? 'Add a filed document' : 'Add a tax document'}
      label=${doc ? 'Save' : 'Add'}
      done=${rec?.removed ? 'Document removed' : doc ? 'Document saved' : 'Document kept'}
      extra=${({ save }) =>
        doc
          ? html`
            <button type="button" class="btn danger" disabled=${save.busy}
              onClick=${async () => {
                if (!rec || !f.draft) return;
                const sure = await confirmAction({
                  title: 'Remove this document?',
                  yes: 'Yes, remove',
                });
                if (!sure) return;
                f.draft.remove(rec);
                const r = await save.run().catch(() => null);
                if (r?.status !== 'saved') f.draft.unremove(rec);
              }}>Remove</button><span class="spacer"></span>
          `
          : null}>
      ${rec
        ? html`
          <div class="field" data-help="direction" id="x-direction"><label>Kind</label>
            <${Seg} label="Kind" value=${rec.get('direction')} onChange=${(
              /** @type {string} */ x,
            ) => {
              rec.set('direction', x);
              rec.set('form', x === 'filed' ? 'Return as filed' : 'W-2', 'direction');
            }} options=${[['received', 'Received'], ['filed', 'Filed']]} /></div>
          <div class="row">
            <${RecField} rec=${rec} name="form" label="Document" id="form"
              options=${filed ? forms.filed : forms.received} />
            <${RecField} rec=${rec} name="issuer" label="Issued by" id="issuer"
              placeholder=${filed ? 'IRS' : 'Acme Corp'} />
          </div>
          <${RecField} rec=${rec} name="filingId" label="Filing" id="filing" options=${[
            ['', 'Choose…'],
            ...b.filings.map((/** @type {any} */ x) => [x.id, x.label]),
          ]} />
          <${RecField} rec=${rec} name="accountId" label="Account" id="account"
            hint="The account it reports on, if any." options=${[
              ['', 'None'],
              ...b.accounts.map((/** @type {any} */ a) => [a.id, a.name]),
            ]} />
          <${Field} label="File" id="file" error=${rec.error('receiptId')}
            hint=${file
              ? `${file.name}, kept with your receipts.`
              : 'The PDF or a photo, kept with your receipts.'}>
            <input class="in" type="file" accept=${ACCEPT} onChange=${async (
              /** @type {any} */ ev,
            ) => {
              const picked = ev.currentTarget.files[0];
              if (!picked) return;
              // Uploaded at once, as a receipt of its own (S12.15.7); kept with it on Save.
              const made = (await uploadAll([picked]))[0];
              if (made) {
                setFile({ name: made.fileName || picked.name });
                rec.set('receiptId', made.id);
              }
            }} /></${Field}>
          <${RecField} rec=${rec} name="notes" label="Notes" rows=${2} />
        `
        : null}
    </${DraftDialog}>
  `;
}
