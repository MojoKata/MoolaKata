// Gifts (requirements S7.7, S7.8, S12.2.8): Upcoming occasions, People, Gifts from idea to given
// (and received), and Spending by person, occasion and year.
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { date, thisYear } from '../app/format.js';
import { useTitle } from '../components/frame.js';
import { useDialogGuide, useGuide } from '../components/help.js';
import { Amt } from '../components/amount.js';
import { Chips, Empty, Failed, Loading, Tabs } from '../components/bits.js';
import { openDialog } from '../components/dialog.js';
import { Field, Input, Seg, Select } from '../components/fields.js';
import { Icon } from '../components/icon.js';
import { ShareDialog } from '../components/share.js';
import { toast } from '../components/toast.js';
import { ACCEPT, uploadAll } from '../components/receipt.js';
import { dec, num } from '../app/dec.js';
import { Record as Rec } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { DraftDialog, RecField, useDraft } from '../components/draft-form.js';

const TABS = /** @type {[string, string][]} */ ([
  ['upcoming', 'Upcoming'],
  ['people', 'People'],
  ['gifts', 'Gifts'],
  ['spending', 'Spending'],
]);
export const STATUS = /** @type {[string, string][]} */ ([
  ['idea', 'Idea'],
  ['planned', 'Planned'],
  ['bought', 'Bought'],
  ['given', 'Given'],
  ['received', 'Received'],
]);
const TONE = /** @type {Record<string, string>} */ ({
  idea: '',
  planned: 'info',
  bought: 'ok',
  given: 'ok',
  received: '',
});

/** @param {{ status: string }} p */
function StatusPill({ status }) {
  return html`<span class=${'pill ' + (TONE[status] || '')}>${
    STATUS.find(([k]) => k === status)?.[1]
  }</span>`;
}

/** @param {{ tab?: string }} p */
export default function Gifts({ tab }) {
  const current = TABS.some(([k]) => k === tab) ? /** @type {string} */ (tab) : 'upcoming';
  useTitle('Gifts');
  useGuide('gifts-' + current);
  return html`
    <${Tabs} tabs=${TABS} current=${current} base="/ui/gifts" />
    ${current === 'upcoming' ? html`<${Upcoming} />` : null}
    ${current === 'people' ? html`<${People} />` : null}
    ${current === 'gifts' ? html`<${GiftList} />` : null}
    ${current === 'spending' ? html`<${Spending} />` : null}
  `;
}

function Upcoming() {
  const res = useList('/gifts/upcoming');
  const rows = /** @type {any[]} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!rows) return html`<${Loading} />`;
  const add = (/** @type {any} */ u) =>
    openDialog(GiftDialog, {
      start: u
        ? { people: [u.person.id], occasion: u.key, occasionYear: u.date.slice(0, 4) }
        : null,
    }).then(res.reload);
  const open = (/** @type {any} */ g) => openDialog(GiftDialog, { gift: g }).then(res.reload);
  return html`
    <div class="card"><h3>Next 60 days<span class="spacer"></span><button class="btn sm"
      onClick=${() => add(null)}><${Icon} name="plus" /> Add a gift</button></h3>
      ${rows.length
        ? rows.map((u) =>
          html`
            <div class="list-item" style=${{ alignItems: 'flex-start' }}>
              <div class="tile t-giving">
                <${Icon} name="gift" />
              </div>
              <div class="grow"><b>${u.person.name}</b> · ${u.label}${u.turns
                ? ` (${u.label === 'Birthday' ? 'turns' : ''} ${u.turns}${
                  u.label === 'Birthday' ? '' : ' years'
                })`
                : ''}
                          <div class="small dim">${date(u.date)} · ${u.days === 0
                            ? 'today'
                            : `in ${u.days} day${u.days === 1 ? '' : 's'}`}${u.inLead
                            ? html`
                              · <span class="pill warn">inside the reminder time</span>
                            `
                            : null}</div>
                          <div class="toolbar" style=${{
                            margin: '6px 0 0',
                            flexWrap: 'wrap',
                          }}>${u.gifts.length
                            ? u.gifts.map((/** @type {any} */ g) =>
                              html`
                                <button type="button" class="chip"
                                  onClick=${() => open(g)}>${g
                                    .description} <${StatusPill} status=${g.status} /></button>
                              `
                            )
                            : html`<span class="small dim">${u.missing}</span>`}</div></div>
              <div
                class="num small"><b><${Amt} v=${u.planned} /></b>${u.budget
                  ? html`<div class="dim">of <${Amt} v=${u.budget} cents=${false} /></div>`
                  : null}<button class="btn sm mt" onClick=${() =>
                  add(
                    u,
                  )} aria-label=${`Add a gift for ${u.person.name}'s ${u.label.toLowerCase()}`}>Add</button></div>
            </div>
          `
        )
        : html`<${Empty}>Nothing in the next 60 days. Add people, with their birthdays,
          anniversaries and holidays, on the People tab.</${Empty}>`}
    </div>
  `;
}

function People() {
  const res = useList('/people', {}, ['share']);
  const rows = /** @type {any[]} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!rows) return html`<${Loading} />`;
  const open = (/** @type {any} */ p) => openDialog(PersonDialog, { p }).then(res.reload);
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <h3 style=${{ padding: '8px 8px 0' }}>People<span class="spacer"></span><button class="btn sm"
        onClick=${() => open(null)}><${Icon} name="plus" /> Add a gift plan</button></h3>
      ${rows.length
        ? html`
          <div class="table-wrap">
            <table class="t">
              <caption class="sr-only">People</caption>
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Next</th>
                  <th class="num">Budget</th>
                  <th class="num">Spent this year</th>
                  <th>Last gift</th>
                </tr>
              </thead>
              <tbody>${rows.map((p) =>
                html`
                  <tr class="click" tabindex="0" onClick=${() => open(p)} onKeyDown=${(
                    /** @type {KeyboardEvent} */ e,
                  ) => e.key === 'Enter' && open(p)}>
                    <td style=${{ whiteSpace: 'nowrap' }}><b>${p.name}</b>${p.private
                      ? html`
                        <span class="pill">private</span>
                      `
                      : null}<div class="small dim">${[
                      p.relation,
                      p.level === 'owner' ? null : `shared by ${p.ownerName}`,
                    ].filter(Boolean).join(' · ')}</div></td>
                    <td class="small">${p.next
                      ? html`${p.next.label} · ${
                        date(p.next.date)
                      }<div class="dim">in ${p.next.days} days</div>`
                      : html`<span class="dim">—</span>`}</td>
                    <td class="num">${p.giftBudget
                      ? html`<${Amt} v=${p.giftBudget} cents=${false} />`
                      : html`<span class="dim">—</span>`}</td>
                    <td class="num">
                      <${Amt} v=${p.spent} cents=${false} />
                    </td>
                    <td class="small dim">${p.lastGift || '—'}</td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        `
        : html`<${Empty}>No people yet. Add the people you give gifts to, with their dates.</${Empty}>`}
    </div>
    <p class="small dim">People are the household's; your gift plans and gifts are yours alone,
      unless you share a plan. A gift for someone who is a user here is never shown to them, even
      through a share.</p>
  `;
}

function GiftList() {
  const [status, setStatus] = useState('');
  const res = useList('/gifts', { status: status || undefined });
  const rows = /** @type {any[]} */ (res.data);
  const open = (/** @type {any} */ g) => openDialog(GiftDialog, { gift: g }).then(res.reload);
  return html`
    <div class="toolbar"><${Chips} label="Show" value=${status} onChange=${setStatus}
      options=${[['', 'All'], ...STATUS]} /><span class="spacer"></span><button
      class="btn primary" onClick=${() =>
        open(null)}><${Icon} name="plus" /> Add a gift</button></div>
    ${res.error ? html`<${Failed} error=${res.error} />` : !rows ? html`<${Loading} />` : rows
        .length
      ? html`
        <div class="card" style=${{ padding: '4px 8px' }}>
          <div class="table-wrap">
            <table
              class="t">
              <caption class="sr-only">Gifts</caption>
              <thead>
                <tr>
                  <th>For</th>
                  <th>Occasion</th>
                  <th>Gift</th>
                  <th>Status</th>
                  <th class="num">Cost</th>
                </tr>
              </thead>
              <tbody>${rows.map((g) =>
                html`
                  <tr class="click" tabindex="0" onClick=${() => open(g)} onKeyDown=${(
                    /** @type {KeyboardEvent} */ e,
                  ) => e.key === 'Enter' && open(g)}>
                    <td style=${{ whiteSpace: 'nowrap' }}>${g.status === 'received'
                      ? 'From '
                      : ''}${g
                      .people.map((/** @type {any} */ p) =>
                        p.deleted ? `${p.name} (deleted)` : p.name
                      ).join(', ')}</td>
                    <td class="small" style=${{ whiteSpace: 'nowrap' }}>${g
                      .occasionLabel}${g.occasionYear ? ` ${g.occasionYear}` : ''}</td>
                    <td>${g.description}${g.status === 'received' && g.thankYou
                      ? html`
                        <span class="small dim">· thanked</span>
                      `
                      : null}</td>
                    <td>
                      <${StatusPill} status=${g.status} />
                    </td>
                    <td class="num">${g.cost ? html`<${Amt} v=${g.cost} />` : html`
                      <span
                        class="dim">—</span>
                    `}</td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        </div>
      `
      : html`<${Empty}>No gifts${status ? ' with that status' : ''} yet.</${Empty}>`}
  `;
}

function Spending() {
  const now = thisYear();
  const [year, setYear] = useState(String(now));
  const res = useApi('/gifts/spending', { year });
  const v = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} />`;
  const most = Math.max(1, ...v.byYear.map((/** @type {any} */ y) => num(y.amount)));
  return html`
    <div class="toolbar">
      <${Chips} label="Year" value=${year} onChange=${setYear}
        options=${[now - 2, now - 1, now].map((y) => [String(y), String(y)])} />
    </div>
    ${v.flagged.length
      ? html`<div class="notice warn">${
        v.flagged.map((/** @type {any} */ f) =>
          html`<div>Money given to ${f.person.name} in ${v.year} comes to <${Amt} v=${f.given}
          cents=${false} />, above the <${Amt} v=${f.exclusion} cents=${false} /> annual
          exclusion: a gift-tax return (Form 709) is needed, even when no tax is due.</div>`
        )
      }</div>`
      : null}
    <div class="grid g-main mt">
      <div class="card"><h3>By person, ${v.year}</h3>${v.byPerson.length
        ? v.byPerson.map((/** @type {any} */ p) => {
          const share = p.budget ? Math.min(100, (num(p.spent) / num(p.budget)) * 100) : 0;
          return html`
            <div class="list-item">
              <div class="grow">${p.person.name}${p.budget
                ? html`<div class="bar" style=${{ marginTop: '6px' }}><i style=${{
                  width: `${share}%`,
                }}></i></div>`
                : null}</div>
              <div class="num small"><b><${Amt} v=${p.spent} cents=${false} /></b>${p
                  .budget
                ? html`<div class="dim">of <${Amt} v=${p.budget} cents=${false} /></div>`
                : null}</div>
            </div>
          `;
        })
        : html`<p class="small dim">No people yet.</p>`}</div>
      <div class="grid" style=${{ alignContent: 'start' }}>
        <div class="card"><h3>By occasion, ${v.year}</h3>${v.byOccasion.length
          ? v.byOccasion.map((/** @type {any} */ o) =>
            html`
              <div
                class="list-item"><span class="grow">${o.label}</span><${Amt} v=${o
                  .amount} cents=${false} /></div>
            `
          )
          : html`<p class="small dim">Nothing bought or given yet.</p>`}</div>
        <div class="card"><h3>By year</h3>${v.byYear.map((/** @type {any} */ y) =>
          html`
            <div
              class="list-item"><span class="small" style=${{ width: '48px' }}>${y
                .label}</span><div class="grow"><div class="bar"><i style=${{
                width: `${(num(y.amount) / most) * 100}%`,
                background: 'var(--hue-giving)',
              }}></i></div></div><span class="num small" style=${{ width: '72px' }}><${Amt}
                        v=${y.amount} cents=${false} /></span></div>
          `
        )}</div>
      </div>
    </div>
  `;
}

/** A person, as a gift plan's dialog edits them (S10.10.1). */
class PersonRec extends Rec {
  /** @override */
  static prefix = 'Persn';
  /** @override */
  static fields = FIELDS.PersonRecord;
  /** @override */
  static defaults = {
    name: '',
    sex: null,
    birthMonth: null,
    birthDay: null,
    birthYear: null,
    diedOn: null,
    private: false,
    differentPerson: false,
  };
}

/** A gift plan (S7.7): it goes with its person. */
class PlanRec extends Rec {
  /** @override */
  static prefix = 'GfPln';
  /** @override */
  static fields = FIELDS.PlanRecord;
  /** @override */
  static defaults = { giftBudget: null, leadDays: 14, notes: null };
  /** @override */
  static ownedBy = ['personId'];
}

/** A plan's occasion: a holiday, or an anniversary or other occasion on a day (S7.7.1). */
class OccasionRec extends Rec {
  /** @override */
  static prefix = 'Occsn';
  /** @override */
  static fields = FIELDS.OccasionRecord;
  /** @override */
  static defaults = { name: null, holiday: null, month: null, day: null, year: null, budget: null };
  /** @override */
  static ownedBy = ['giftPlanId'];
}

/** A day as typed, "2018-10-20" or "10-20" without the year, shown back the same way. */
const DAY = {
  /** @param {string} s */
  read(s) {
    if (!s.trim()) return { value: { month: null, day: null, year: null } };
    const m = s.trim().match(/^(?:(\d{4})-)?(\d{1,2})-(\d{1,2})$/);
    if (!m) return { error: 'Type 2018-10-20, or 10-20 without the year.' };
    return { value: { year: m[1] ? Number(m[1]) : null, month: Number(m[2]), day: Number(m[3]) } };
  },
  /** @param {number | null} y @param {number | null} m @param {number | null} d */
  show: (y, m, d) =>
    m ? `${y ? y + '-' : ''}${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}` : '',
};

/** @param {string} prefix */
const asFields = (/** @type {any} */ v, /** @type {string} */ prefix) =>
  Object.fromEntries(
    Object.entries(v).map(([k, x]) => [prefix + k[0].toUpperCase() + k.slice(1), x]),
  );

/** @param {{ close: (v?: any) => void, p: any }} p */
function PersonDialog({ close, p }) {
  useDialogGuide('dialog-person');
  const hols = useList('/holidays');
  const f = useDraft(async (draft) => {
    if (!p) {
      const who = draft.add(PersonRec);
      draft.add(PlanRec, { personId: who.id });
      return;
    }
    const x = await api.get(`/people/${p.id}`);
    draft.load(PersonRec, {
      id: x.id,
      version: x.personVersion,
      ...Object.fromEntries(Object.keys(PersonRec.defaults).map((k) => [k, x[k] ?? null])),
      private: x.private,
      differentPerson: false,
    });
    draft.load(PlanRec, {
      id: x.planId,
      version: x.version,
      personId: x.id,
      giftBudget: x.giftBudget,
      leadDays: x.leadDays,
      notes: x.notes,
    });
    for (const o of x.occasions) draft.load(OccasionRec, { ...o, giftPlanId: x.planId });
  }, [p?.id]);
  const draft = f.draft;
  const who = /** @type {PersonRec | undefined} */ (
    draft?.records.find((r) => r instanceof PersonRec)
  );
  const plan = /** @type {PlanRec | undefined} */ (
    draft?.records.find((r) => r instanceof PlanRec)
  );
  const occasions = /** @type {OccasionRec[]} */ (
    (draft?.records || []).filter((r) => r instanceof OccasionRec)
  );
  const dated = occasions.filter((o) => !o.removed && o.get('kind') !== 'holiday');
  const canWrite = !p || p.level !== 'read';
  const ownPerson = !p || p.canChangePerson;
  // One person, once (S10.10.3): a name already here shows that person instead.
  const [clash, setClash] = useState(/** @type {any} */ (null));
  const [using, setUsing] = useState(false);
  useEffect(() => {
    if (!who || who.state !== 'new' || !who.error('name')) return;
    api.get('/persons/clash', { name: who.get('name'), birthYear: who.get('birthYear') ?? '' })
      .then(setClash, () => {});
  }, [who?.error('name')]);
  /** The plan for someone already here: the new person goes. */
  const use = () => {
    if (!who || !plan || !draft) return;
    plan.set('personId', clash.id);
    draft.remove(who);
    setUsing(true);
  };
  /** Typing the name again: a new person after all. */
  const unuse = () => {
    setClash(null);
    if (!who || !plan || !draft || !using) return;
    draft.unremove(who);
    plan.set('personId', who.id);
    setUsing(false);
  };
  const holiday = (/** @type {string} */ key) =>
    occasions.find((o) => o.get('kind') === 'holiday' && o.get('holiday') === key);
  const toggle = (/** @type {string} */ key) => {
    if (!draft || !plan) return;
    const o = holiday(key);
    if (!o) draft.add(OccasionRec, { giftPlanId: plan.id, kind: 'holiday', holiday: key });
    else if (o.removed) draft.unremove(o);
    else draft.remove(o);
  };
  // Deleting asks twice: the plan only, or the person with it (S7.8.6).
  const [armed, setArmed] = useState('');
  const join = useSubmit(async (/** @type {any} */ r) => {
    await api.post(`/persons/${p.id}/join`, { userId: r.id });
    toast(`${r.name} on ${r.server} is ${p.name} here`);
    close(true);
  });
  const ask = useSubmit(async () => {
    await api.post(`/persons/${clash.id}/ask-to-share`);
    toast(`Asked ${clash.createdBy || 'an admin'} to share ${clash.name}`);
    close();
  });
  const rels = useApi(p ? `/persons/${p.id}/relations` : null, {});
  const relations = /** @type {any[]} */ ((/** @type {any} */ (rels.data))?.items || []);
  const birthday = who
    ? who.typed('birthday') ??
      DAY.show(who.get('birthYear'), who.get('birthMonth'), who.get('birthDay'))
    : '';
  const deleting = (plan?.removed && !using) ? (who?.removed ? 'person' : 'plan') : '';
  return html`
    <${DraftDialog} f=${f} wide close=${close} what="This gift plan"
      title=${p ? `Gift plan for ${p.name}` : 'New gift plan'}
      done=${deleting === 'person'
        ? `${p?.name} deleted`
        : deleting
        ? 'Gift plan deleted'
        : p
        ? 'Saved'
        : `${who?.get('name') || 'They'} added`}
      hideSave=${!canWrite}
      extra=${({ save }) => {
        /** Delete the plan, or the person with it: armed first, then removed and saved. */
        const drop = async (/** @type {string} */ what) => {
          if (armed !== what || !draft) return setArmed(what);
          const r = /** @type {any} */ (what === 'person' ? who : plan);
          draft.remove(r);
          const out = await save.run().catch(() => null);
          if (out?.status !== 'asks' && out?.status !== 'saved') draft.unremove(r);
        };
        return html`${
          p && p.level === 'owner'
            ? html`<button type="button" class="btn" onClick=${() =>
              openDialog(ShareDialog, {
                kind: 'gift-plan',
                id: p.planId,
                name: `Gift plan for ${p.name}`,
              })}><${Icon} name="share" /> Share</button>`
            : null
        }${
          p && p.level === 'owner'
            ? html`
              <button type="button" class="btn danger" disabled=${save.busy}
                onClick=${() => drop('plan')}>${armed === 'plan'
                  ? 'Delete the plan?'
                  : 'Delete plan'}</button>
            `
            : null
        }${
          p && p.canChangePerson && !p.isUser
            ? html`
              <button type="button" class="btn danger" disabled=${save.busy}
                onClick=${() => drop('person')}>${armed === 'person'
                  ? `Delete ${p.name} for everyone?`
                  : 'Delete person'}</button>
            `
            : null
        }<span class="spacer"></span>`;
      }}>
      ${(p?.sameAs || []).map((/** @type {any} */ r) =>
        html`<div class="notice" role="status" key=${r.id} style=${{
          marginBottom: '12px',
        }}><${Icon}
          name="link" /><div class="grow">
          ${r.name} on ${r.server} may be ${p.name}. Joined, the linked server's user is this
          person here, and ${p.name} stays as private as now.</div><button type="button"
            class="btn sm" disabled=${join.busy} onClick=${() =>
          join.run(r).catch(() => {})}>Join them</button></div>`
      )}
      ${who && plan
        ? html`
          <fieldset disabled=${!canWrite} style=${{
            border: 0,
            padding: 0,
            margin: 0,
            minWidth: 0,
          }}>
            <fieldset disabled=${!ownPerson || using} class="card" style=${{
              margin: '0 0 12px',
              padding: '10px 12px',
              minWidth: 0,
            }} data-help="the-person">
              <div class="small dim">The person, seen by the household${p?.private
                ? ' (private: only those it is shared with)'
                : ''}</div>
              <div class="row">
                <${RecField} rec=${who} name="name" label="Name" placeholder="Emma Griffin"
                  onEdit=${unuse} />
                <${RecField} rec=${who} name="sex" label="Sex" options=${[
                  ['', 'Choose…'],
                  ['female', 'Female'],
                  ['male', 'Male'],
                ]} />
                <${Field} label="Birthday" error=${who.error('birthday') ||
                  who.error('birthDay') || who.error('birthMonth') || who.error('birthYear')}
                  hint="2018-10-20, or 10-20 without the year.">
                  <${Input} value=${birthday} placeholder="YYYY-MM-DD" onInput=${(
                    /** @type {string} */ v,
                  ) =>
                    who.inputAs(
                      'birthday',
                      v,
                      (t) => {
                        const r = DAY.read(t);
                        return 'error' in r ? r : { value: asFields(r.value, 'birth') };
                      },
                    )} />
                </${Field}>
              </div>
              <div class="row">
                <${RecField} rec=${who} name="diedOn" label="Died on" id="died-on" type="date"
                  hint="Ends a marriage on that day; their gifts stay in the history." />
                ${!p || p.canMakePrivate
                  ? html`
                    <${RecField} rec=${who} name="private" label="Private"
                      hint="Seen only by you and whoever you share them with." />
                  `
                  : null}
              </div>
              <div class="small">${p?.relation
                ? html`<b>${p.relation[0].toUpperCase() + p.relation.slice(1)}</b> to you, worked
                  out from relationships.`
                : 'How they’re related to you is worked out from relationships.'}</div>
              ${relations.length
                ? html`
                  <div class="small dim" data-help="their-relationships"
                    style=${{
                      marginTop: '6px',
                    }}>${p.name.split(' ')[0]}'s family and friends: ${relations.map((
                      /** @type {any} */ r,
                    ) => `${r.name} (${r.label || r.word})`).join(', ')}</div>
                `
                : null}
            </fieldset>
            ${clash && !using
              ? html`
                <div class="notice" role="status">
                  <${Icon} name="info" />
                  <div><b>${clash.name} is already here</b>${clash.visible
                    ? html`. <button type="button" class="btn sm" onClick=${use}>Use ${clash.name}</button>`
                    : html`
                      , kept private by ${clash.createdBy || 'someone'}. <button type="button"
                        class="btn sm" disabled=${ask.busy} onClick=${() =>
                          ask.run().catch(() => {})}>Ask to share</button>
                    `} <button type="button" class="btn sm" onClick=${() =>
                    who.set('differentPerson', true)}>A different person</button>
                    ${who.get('differentPerson')
                      ? html`<div class="small">Give a birth year above that differs from theirs.</div>`
                      : null}</div>
                </div>
              `
              : using
              ? html`
                <div class="notice">
                  <${Icon} name="info" />
                  <div>A gift plan for ${who.get('name')}, who is already here.</div>
                </div>
              `
              : null}
            <div class="row">
              <${RecField} rec=${plan} name="giftBudget" label="Yearly gift budget" id="gift-budget"
                placeholder="600" />
            </div>
            <div class="field" data-help="holidays" id="x-holidays"><label>Holidays</label>
              <div class="chips" style=${{
                flexWrap: 'wrap',
              }}>${(/** @type {any[]} */ (hols.data) || []).map((h) => {
                const on = !!holiday(h.key) && !holiday(h.key)?.removed;
                return html`
                  <button type="button" class=${'chip' + (on ? ' on' : '')}
                    aria-pressed=${on ? 'true' : 'false'} onClick=${() => toggle(h.key)}>${h
                      .label}</button>
                `;
              })}</div></div>
            <div class="toolbar"><b class="small" data-help="dates">Anniversaries and other
                dates</b><span class="spacer"></span><button type="button" class="btn sm"
                onClick=${() =>
                  draft?.add(OccasionRec, { giftPlanId: plan.id, kind: 'anniversary' })}><${Icon}
                name="plus" /> Add a date</button></div>
            ${dated.map((o, i) =>
              html`
                <div class="row" key=${o.key}>
                  <${Field} label="What" help="dates" id=${'date-kind-' + i}>
                    <${RecField} rec=${o} name="kind" bare label="What" options=${[
                      ['anniversary', 'Anniversary'],
                      ['custom', 'Other occasion'],
                    ]} />
                    </${Field}>
                    <${Field} label="Called" help="dates" id=${'date-name-' + i}
                      error=${o.error('name')}>
                      <${RecField} rec=${o} name="name" bare label="Called"
                        placeholder=${o.get('kind') === 'anniversary' ? 'Wedding' : 'Name day'} />
                      </${Field}>
                      <${Field} label="On" help="dates" id=${'date-on-' + i}
                        error=${o.error('on') || o.error('month')}>
                        <${Input} value=${o.typed('on') ??
                          DAY.show(o.get('year'), o.get('month'), o.get('day'))}
                          placeholder="YYYY-MM-DD" aria-label="On"
                          onInput=${(/** @type {string} */ v) => o.inputAs('on', v, DAY.read)} />
                        </${Field}>
                        <${Field} label="Budget" help="dates" id=${'date-budget-' + i}
                          error=${o.error('budget')}>
                          <${RecField} rec=${o} name="budget" bare label="Budget" />
                          </${Field}>
                          <button type="button" class="icon-btn" aria-label="Remove the date"
                            onClick=${() => draft?.remove(o)}><${Icon} name="x" /></button>
                          </div>
              `
            )}
            <${RecField} rec=${plan} name="leadDays" label="Remind me" id="lead-days" options=${[
              ['7', '7 days before'],
              ['14', '14 days before'],
              ['30', '30 days before'],
            ]} />
            <${RecField} rec=${plan} name="notes" label="Notes" rows=${3}
              hint="Sizes, likes, what they already have." />
          </fieldset>
        `
        : null}
      ${p ? html`<${History} p=${p} />` : null}
    </${DraftDialog}>
  `;
}

/** What was given a person in past years, so it isn't given twice. */
/** @param {{ p: any }} p */
function History({ p }) {
  const res = useList('/gifts', { person: p.id, status: 'given' });
  const rows = /** @type {any[]} */ (res.data) || [];
  if (!rows.length) return null;
  return html`<h4 style=${{ margin: '14px 0 8px' }} data-help="given-before">Given before</h4>
    ${
    rows.map((g) =>
      html`<div class="list-item"><span class="grow">${g.description}<span class="small dim">
        · ${g.occasionLabel} ${g.occasionYear || ''}</span></span>${
        g.cost ? html`<${Amt} v=${g.cost} />` : null
      }</div>`
    )
  }`;
}

/** A gift (S7.8), as its dialog's draft edits it, its receipts kept with it. */
class GiftRec extends Rec {
  /** @override */
  static prefix = 'Gift';
  /** @override */
  static fields = FIELDS.GiftRecord;
  /** @override */
  static defaults = {
    occasion: null,
    occasionYear: null,
    status: 'idea',
    cost: null,
    transactionId: null,
    store: null,
    link: null,
    notes: null,
    cash: false,
    thankYou: false,
    receiptIds: [],
  };
  /** @override */
  static rules = {
    // A thank-you is for a gift received.
    thankYou: {
      when: (/** @type {GiftRec} */ r) => r.get('status') === 'received',
      otherwise: false,
    },
  };
}

/** @param {{ close: (v?: any) => void, gift?: any, start?: any }} p */
function GiftDialog({ close, gift, start }) {
  useDialogGuide('dialog-gift');
  const people = useList('/people');
  const buys = useList('/gifts/purchases');
  const f = useDraft((draft) => {
    if (gift) {
      draft.load(GiftRec, {
        ...gift,
        people: gift.people.map((/** @type {any} */ p) => p.id),
        transactionId: gift.paid?.transactionId ?? null,
        receiptIds: gift.documents.map((/** @type {any} */ d) => d.id),
      });
      return;
    }
    draft.add(GiftRec, {
      description: '',
      people: start?.people || [],
      occasion: start?.occasion || null,
      occasionYear: start?.occasionYear || null,
      status: start ? 'planned' : 'idea',
    });
  }, [gift?.id]);
  const rec = /** @type {GiftRec | undefined} */ (f.draft?.records[0]);
  const list = /** @type {any[]} */ (people.data) || [];
  const canWrite = !gift || gift.canWrite;
  const year = thisYear();
  const who = /** @type {string[]} */ (rec?.get('people') || []);
  // The occasions of the chosen people, this year and next.
  const chosen = list.filter((p) => who.includes(p.id));
  /** @type {[string, string][]} */
  const occasions = [['', 'No date (an idea)']];
  for (const y of [year, year + 1]) {
    const keys = new Map();
    for (const p of chosen) {
      if (p.birthMonth) keys.set('birthday', 'Birthday');
      if (p.wedding) keys.set('wedding', 'Wedding anniversary');
      for (const o of p.occasions) {
        keys.set(o.kind === 'holiday' ? `holiday:${o.holiday}` : `occasion:${o.id}`, o.label);
      }
    }
    for (const [k, l] of keys) occasions.push([`${k}|${y}`, `${l} ${y}`]);
  }
  const occasion = rec?.get('occasion') ? `${rec.get('occasion')}|${rec.get('occasionYear')}` : '';
  if (occasion && !occasions.some(([k]) => k === occasion)) {
    occasions.push([occasion, `${gift?.occasionLabel || 'Occasion'} ${rec?.get('occasionYear')}`]);
  }
  const [busy, setBusy] = useState(false);
  const ids = /** @type {string[]} */ (rec?.get('receiptIds') || []);
  const send = async (/** @type {FileList} */ files) => {
    setBusy(true);
    try {
      const made = await uploadAll(files);
      rec?.set('receiptIds', [...ids, ...made.map((r) => r.id)]);
    } finally {
      setBusy(false);
    }
  };
  const received = rec?.get('status') === 'received';
  return html`
    <${DraftDialog} f=${f} close=${close} what="This gift" hideSave=${!canWrite}
      title=${gift ? gift.description : 'Add a gift'}
      done=${rec?.removed ? 'Gift deleted' : 'Gift saved'}
      extra=${({ save }) =>
        gift && canWrite
          ? html`
            <button type="button" class="btn danger" disabled=${save.busy}
              onClick=${async () => {
                if (!rec || !f.draft) return;
                f.draft.remove(rec);
                const r = await save.run().catch(() => null);
                if (r?.status !== 'saved') f.draft.unremove(rec);
              }}>Delete</button><span class="spacer"></span>
          `
          : null}>
      ${rec
        ? html`
          <fieldset disabled=${!canWrite} style=${{
            border: 0,
            padding: 0,
            margin: 0,
            minWidth: 0,
          }}>
            <div class="field" data-help="status" id="x-status"><label>Status</label>
              <${Seg} label="Status" value=${rec.get('status')} onChange=${(
                /** @type {string} */ v,
              ) => rec.set('status', v)} options=${STATUS} /></div>
            <${Field} label=${received ? 'From' : 'For'} id="people" error=${rec.error('people')}
              hint=${received ? '' : 'One or more people.'}>
              <select class="in" multiple size=${Math.min(4, Math.max(2, list.length))}
                onChange=${(/** @type {any} */ ev) =>
                  rec.set('people', [...ev.currentTarget.selectedOptions].map((o) => o.value))}>
                ${list.map((p) =>
                  html`<option value=${p.id} selected=${who.includes(p.id)}>${p.name}</option>`
                )}</select></${Field}>
            <${Field} label="Occasion" error=${rec.error('occasionYear')}>
              <${Select} value=${occasion} onChange=${(/** @type {string} */ v) => {
                const [occ, y] = v ? v.split('|') : [null, null];
                rec.set('occasion', occ);
                rec.set('occasionYear', y ? Number(y) : null);
              }} options=${occasions} /></${Field}>
            <${RecField} rec=${rec} name="description" label="Description"
              placeholder="Watercolour set" />
            ${received
              ? html`<${RecField} rec=${rec} name="thankYou" label="Thank-you sent" />`
              : html`
                <div class="row">
                  <${RecField} rec=${rec} name="cost" label="Cost" />
                  <${Field} label="Paid with" id="paid-with" error=${rec.error('transactionId')}
                    hint="Its transaction; one purchase can pay for several gifts.">
                    <${Select} value=${rec.get('transactionId') || ''} onChange=${(
                      /** @type {string} */ x,
                    ) => {
                      const t = (/** @type {any[]} */ (buys.data) || []).find((b) =>
                        b.transactionId === x
                      );
                      rec.set('transactionId', x || null);
                      if (rec.get('cost') == null && t) {
                        rec.set('cost', dec(t.amount).neg(), 'transactionId');
                      }
                    }} options=${[
                      ['', 'Typed, or not bought yet'],
                      ...(gift?.paid &&
                          !(/** @type {any[]} */ (buys.data) || []).some((b) =>
                            b.transactionId === gift.paid.transactionId
                          )
                        ? [[
                          gift.paid.transactionId,
                          `${gift.paid.payee || 'Purchase'} · ${date(gift.paid.date)}`,
                        ]]
                        : []),
                      ...(/** @type {any[]} */ (buys.data) || []).map((b) => [
                        b.transactionId,
                        `${b.payee || 'Purchase'} · ${date(b.date)} · ${b.accountName} ${b.amount}`,
                      ]),
                    ]} />
                    </${Field}>
                    </div>
                    <${RecField} rec=${rec} name="cash" label="Given in money"
                      hint="Cash or a cheque: counted against the annual gift exclusion." />
                    <div class="row">
                      <${RecField} rec=${rec} name="store" label="Where bought" id="store" />
                      <${RecField} rec=${rec} name="link" label="Link" placeholder="https://" />
                    </div>
              `}
            <${RecField} rec=${rec} name="notes" label="Notes" rows=${2} />
          </fieldset>
          ${gift && canWrite
            ? html`
              <div class="toolbar"><label class="btn sm" for="f-gift-files"><${Icon}
                name="clip" /> ${busy
                  ? 'Uploading…'
                  : `Attach a receipt${ids.length ? ` (${ids.length})` : ''}`}</label><input
                  id="f-gift-files" class="sr-only" type="file" multiple accept=${ACCEPT}
                  data-help="receipts" onChange=${(/** @type {any} */ ev) => {
                    send(ev.currentTarget.files);
                    ev.currentTarget.value = '';
                  }} /></div>
            `
            : null}
        `
        : null}
    </${DraftDialog}>
  `;
}
