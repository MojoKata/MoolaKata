// Settings › Storage (requirements S16.17, S14.10): the database's and the files' sizes, the
// files expired against the rest, what expires each coming year by category, how long
// statements are kept, each category's period, and Prune. Sizes and counts only, never what
// the files hold.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { withReauth } from './reauth.js';
import { Failed, Loading } from './bits.js';
import { Dialog, openDialog } from './dialog.js';
import { errAt, Field, FormError, Input } from './fields.js';
import { useDialogGuide } from './help.js';
import { toast } from './toast.js';
import { Record } from '../app/draft.js';
import { DraftDialog, DraftForm, RecField, useDraft } from './draft-form.js';
import { useSettingsDraft } from './settings-draft.js';
import { FIELDS } from '../api/fields.js';

const COLORS = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)', 'var(--c5)', 'var(--c6)'];

/** @param {number} n */
export const size = (n) =>
  n >= 1073741824
    ? (n / 1073741824).toFixed(1) + ' GB'
    : n >= 1048576
    ? (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + ' MB'
    : Math.ceil(n / 1024) + ' KB';

/** @param {number} n */
const count = (n) => n.toLocaleString('en-US');

/**
 * A ring of parts, with its legend.
 * @param {{ parts: { name: string, value: number, color: string, note: string }[] }} p
 */
function Ring({ parts }) {
  const total = parts.reduce((a, x) => a + x.value, 0) || 1;
  const r = 60, c = 2 * Math.PI * r;
  let at = 0;
  return html`
    <div class="row" style=${{ alignItems: 'center', gap: '24px' }}>
      <svg width="160" height="160" viewBox="0 0 160 160" role="img"
        aria-label=${parts.map((x) => `${x.name}: ${x.note}`).join('; ')}>
        <circle cx="80" cy="80" r=${r} fill="none" stroke="var(--border)" stroke-width="22" />
        ${parts.map((x) => {
          const len = (x.value / total) * c;
          const el = html`
            <circle cx="80" cy="80" r=${r} fill="none" stroke=${x.color}
              stroke-width="22" stroke-dasharray=${`${len} ${c - len}`}
              stroke-dashoffset=${-at} transform="rotate(-90 80 80)" />
          `;
          at += len;
          return el;
        })}
      </svg>
      <div class="legend" style=${{ display: 'grid', gap: '6px' }}>${parts.map((x) =>
        html`<span><i style=${{ background: x.color }}></i>${x.name} · ${x.note}</span>`
      )}</div>
    </div>
  `;
}

/**
 * Stacked bars, one per year, by category.
 * @param {{ years: any[] }} p
 */
function YearBars({ years }) {
  const names = [...new Set(years.flatMap((y) => y.categories.map((c) => c.category)))];
  const color = (/** @type {string} */ n) => COLORS[names.indexOf(n) % COLORS.length];
  const top = Math.max(1, ...years.map((y) => y.categories.reduce((a, c) => a + c.bytes, 0)));
  return html`
    <div style=${{ display: 'flex', alignItems: 'flex-end', gap: '10px', height: '160px' }}
      role="img" aria-label="What expires each year">
      ${years.map((y) =>
        html`
          <div style=${{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div style=${{
              display: 'flex',
              flexDirection: 'column-reverse',
              width: '100%',
              maxWidth: '36px',
              height: '130px',
            }}>${y.categories.map((c) =>
              html`
                <div title=${`${c.category}: ${count(c.files)} files, ${size(c.bytes)}`}
                  style=${{
                    height: `${(c.bytes / top) * 100}%`,
                    background: color(c.category),
                  }}></div>
              `
            )}</div>
            <div class="small dim">${y.year}</div>
          </div>
        `
      )}
    </div>
    <div class="legend">${names.map((n) =>
      html`<span><i style=${{ background: color(n) }}></i>${n}</span>`
    )}</div>
  `;
}

export function StorageSection() {
  const res = useApi('/settings/storage');
  const s = useApi('/settings');
  const v = /** @type {any} */ (res.data);
  const fd = useSettingsDraft(s.data, ['keepStatementsYears']);
  const rec = fd.rec;
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v || !rec) return html`<${Loading} />`;
  const years = rec.get('keepStatementsYears');
  const prune = () => openDialog(PruneDialog, { v }).then((x) => x && res.reload());
  return html`
    <div class="grid" style=${{ alignContent: 'start' }}>
      <${DraftForm} f=${fd} class="card" where="Settings › Storage" what="These settings"
        saved=${() => {
          toast('Saved');
          s.reload();
          res.reload();
        }}>
        <h3>Storage<span class="spacer"></span>${v.expired.files
          ? html`<button type="button" class="btn" onClick=${prune}>Prune ${
            count(
              v.expired.files,
            )
          } files (${size(v.expired.bytes)})</button>`
          : null}</h3>
        <p class="small dim" style=${{ marginTop: '-6px' }}>Records are never removed. Receipt and
          statement files are kept as long as their category says, counted from when their record
          ended, and for ever by default. Files are never pruned on their own.</p>
        <div class="list-item"><span class="grow">Database</span><b>${size(
          v.databaseBytes,
        )}</b></div>
        <div class="list-item"><span class="grow">Receipts and statements</span><b>${size(
          v.receiptsBytes,
        )}</b></div>
        <${Field} label="Keep statements for" id="keep-statements-years"
          error=${rec.error('keepStatementsYears')}
          hint="Years after each statement's period. Empty keeps them for ever.">
          <${Input} value=${years ?? ''} onInput=${(/** @type {string} */ x) =>
            rec.set('keepStatementsYears', x.trim() ? Number(x) : null)} inputmode="numeric"
            placeholder="for ever" />
          </${Field}>
          </${DraftForm}>
          <div
            class="card"><h3 data-help="files">Receipt and statement files</h3><${Ring} parts=${[
              {
                name: 'Expired, can be pruned',
                value: v.expired.bytes,
                color: 'var(--c4)',
                note: `${count(v.expired.files)} · ${size(v.expired.bytes)}`,
              },
              {
                name: 'Expires later',
                value: v.later.bytes,
                color: 'var(--c7)',
                note: `${count(v.later.files)} · ${size(v.later.bytes)}`,
              },
              {
                name: 'Kept for ever',
                value: v.forever.bytes,
                color: 'var(--c1)',
                note: `${count(v.forever.files)} · ${size(v.forever.bytes)}`,
              },
            ]} />${v.orphans.files
              ? html`<div class="list-item"><span class="grow">${
                count(v.orphans.files)
              } files no record names
                  <div class="small dim">Left behind when an older database was restored under files written later.</div></span>${
                size(v.orphans.bytes)
              } <button type="button" class="btn sm" onClick=${() =>
                withReauth(() => api.post('/settings/storage/orphans/remove')).then((out) => {
                  toast(`${count(out.files)} files removed, ${size(out.bytes)} freed`);
                  res.reload();
                }, (e) => toast(e.message))}>Remove</button></div>`
              : null}${v.pruned
              ? html`<p class="small dim">${count(v.pruned)} files pruned before.</p>`
              : null}</div>
          <div class="card"><h3 data-help="what-expires-each-year">What expires each year</h3><p
        class="small dim" style=${{ marginTop: '-6px' }}>By category, from the periods set now.
        Change a category's period and these move.</p>${v.byYear.length
          ? html`<${YearBars} years=${v.byYear} />`
          : html`<p class="small dim">Nothing expires: every file is kept for ever or while its
          record is open.</p>`}</div>
          <${CategoryPeriods} reload=${res.reload} />
          </div>
  `;
}

/** Each category's *Keep receipts for* (S14.10.1.1). @param {{ reload: () => void }} p */
function CategoryPeriods({ reload }) {
  const cats = useList('/categories');
  const list = /** @type {any[] | null} */ (cats.data);
  if (!list) return null;
  const open = (/** @type {any} */ c) =>
    openDialog(CategoryDialog, { c, cats: list }).then((x) => {
      if (x) {
        cats.reload();
        reload();
      }
    });
  const parent = (/** @type {any} */ c) => list.find((x) => x.id === c.parentId);
  return html`
    <div class="card">
      <h3 data-help="keep-receipts-for">Keep receipts for</h3>
      <p class="small dim" style=${{ marginTop: '-6px' }}>Years after the record a receipt is
        attached to ended. A subcategory without its own takes its parent's.</p>
      <div class="table-wrap">
        <table class="t">
          <tbody>${list.filter((c) => c.kind !== 'transfer')
            .map((c) => {
              const own = c.keepReceiptsYears;
              const from = own == null && c.parentId ? parent(c)?.keepReceiptsYears : null;
              return html`
                <tr class="click" onClick=${() => open(c)}>
                  <td>${c.path}</td>
                  <td
                    class="num">${own != null
                      ? `${own} years`
                      : from != null
                      ? html`<span class="dim">${from} years, its parent's</span>`
                      : html`<span class="dim">for ever</span>`}</td>
                </tr>
              `;
            })}</tbody>
        </table>
      </div>
    </div>
  `;
}

/** A category (S2.5), as its dialog's draft edits how long its receipts are kept. */
class CategoryRec extends Record {
  /** @override */
  static prefix = 'Cat';
  /** @override */
  static fields = FIELDS.CategoryRecord;
}

/** @param {{ close: (v?: any) => void, c: any, cats: any[] }} p */
function CategoryDialog({ close, c }) {
  useDialogGuide('dialog-category');
  const f = useDraft((draft) => {
    draft.load(CategoryRec, c);
  }, [c.id]);
  const rec = /** @type {CategoryRec | undefined} */ (f.draft?.records[0]);
  const years = rec?.get('keepReceiptsYears');
  return html`
    <${DraftDialog} f=${f} title=${c.path} close=${close} what="This category" done="Saved">
      ${rec
        ? html`
          <${RecField} rec=${rec} name="keepReceiptsYears" label="Keep receipts for"
            id="keep-receipts-years" placeholder="for ever" hint=${years != null && years < 7
              ? html`<b>Under 7 years:</b> 7 covers every IRS audit window.`
              : 'Years after the record a receipt is attached to ended. Empty keeps them for ever, or as its parent says.'} />
        `
        : null}
    </${DraftDialog}>
  `;
}

/** Prune the expired files (S14.10.5). @param {{ close: (v?: any) => void, v: any }} p */
function PruneDialog({ close, v }) {
  useDialogGuide('dialog-prune');
  const [ticked, setTicked] = useState(v.expiredBy.map((/** @type {any} */ x) => x.category));
  const [typed, setTyped] = useState('');
  const [needPassword, setNeed] = useState(false);
  const [password, setPassword] = useState('');
  const chosen = v.expiredBy.filter((/** @type {any} */ x) => ticked.includes(x.category));
  const files = chosen.reduce((/** @type {number} */ a, /** @type {any} */ x) => a + x.files, 0);
  const bytes = chosen.reduce((/** @type {number} */ a, /** @type {any} */ x) => a + x.bytes, 0);
  const run = useSubmit(async () => {
    if (needPassword) await api.post('/session/reauth', { password });
    try {
      const out = await api.post('/settings/storage/prune', {
        categories: ticked,
        count: Number(typed.replace(/[,\s]/g, '')),
      });
      toast(`${count(out.files)} files pruned, ${size(out.bytes)} freed`);
      close(out);
    } catch (e) {
      if (/** @type {any} */ (e).code === 'reauth-required') {
        setNeed(true);
        return;
      }
      throw e;
    }
  });
  const toggle = (/** @type {string} */ k) =>
    setTicked(ticked.includes(k) ? ticked.filter((x) => x !== k) : [...ticked, k]);
  return html`
    <${Dialog} title=${`Prune ${count(files)} files`} close=${close}
      onSubmit=${() => run.run().catch(() => {})}
      footer=${html`<button class="btn danger" disabled=${run.busy || !files}>Prune</button>`}>
      <p class="small dim" style=${{ marginTop: 0 }}>These files have passed their retention. Their
        records stay, with amounts, dates and links, marked <i>File pruned</i>.</p>
      ${v.expiredBy.map((/** @type {any} */ x) =>
        html`<label class="list-item" style=${{ cursor: 'pointer' }}><input type="checkbox"
          checked=${ticked.includes(x.category)} onChange=${() => toggle(x.category)} /> <span
          class="grow">${x.category}</span>${count(x.files)} files · ${size(x.bytes)}</label>`
      )}
      <div class="list-item"><span class="grow"><b>Space freed</b></span><b>${size(bytes)}</b></div>
      <div class="notice mt" role="note"><div>No backup is made first: a backup holds no files.
        A pruned file survives only in the host's own backups of the data directory.</div></div>
      <${Field} label="Type the number of files to confirm" id="prune-count"
        error=${errAt(run.error, 'count')}>
        <${Input} value=${typed} onInput=${setTyped} inputmode="numeric" placeholder=${count(files)}
          required />
      </${Field}>
      ${needPassword
        ? html`
          <${Field} label="Your password" id="reauth-password"
            hint="Asked again: it was over 10 minutes ago.">
            <${Input} type="password" value=${password} onInput=${setPassword}
              autocomplete="current-password" required />
            </${Field}>
        `
        : null}
      <${FormError} error=${run.error} shown=${['count']} />
    </${Dialog}>
  `;
}
