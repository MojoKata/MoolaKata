// The household's categories (requirements S7.2): the tree on Budgets › Categories, a category's
// dialog (its name, parent, kind and tax tag, each locked with why when the reader may not
// change it, S7.2.3), an admin's merge (S7.2.4), and **New category…** at the end of every list
// of categories to choose from (S12.2.6).
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useList, useSubmit } from '../app/hooks.js';
import { Record } from '../app/draft.js';
import { changes } from '../app/stream.js';
import { FIELDS } from '../api/fields.js';
import { slug } from '../app/format.js';
import { session } from '../store/session.js';
import { confirmAction } from './confirm.js';
import { Dialog, openDialog } from './dialog.js';
import { DraftDialog, RecField, useDraft } from './draft-form.js';
import { Field, FormError, Select } from './fields.js';
import { useDialogGuide } from './help.js';
import { Icon } from './icon.js';
import { Failed, Loading } from './bits.js';
import { toast } from './toast.js';
import { categoryOptions, defaultMapping, mergeTargets, NEW } from '../app/categories.js';

export { categoryOptions, defaultMapping, mergeTargets, NEW };

export const KINDS = /** @type {[string, string][]} */ ([
  ['expense', 'Expense'],
  ['income', 'Income'],
  ['savings', 'Savings'],
  ['transfer', 'Transfer'],
]);

export const TAX_TAGS = /** @type {[string, string][]} */ ([
  ['', 'None'],
  ['charitable', 'Charitable gifts'],
  ['medical', 'Medical and dental'],
  ['business', 'Business expenses'],
  ['childcare', 'Childcare'],
  ['education', 'Education'],
  ['loan-interest', 'Loan interest'],
  ['property-tax', 'Property tax'],
  ['retirement', 'Retirement contributions'],
]);

const KIND_NAMES = Object.fromEntries(KINDS);
const TAG_NAMES = Object.fromEntries(TAX_TAGS);

/**
 * The categories, loaded again when any page changes them (S12.6).
 * @returns {{ list: any[], byId: { [id: string]: any }, loaded: boolean, error: any,
 *   reload: () => void }}
 */
export function useCategories() {
  const r = useList('/categories', {}, ['category']);
  const list = /** @type {any[]} */ (r.data) || [];
  return {
    list,
    byId: Object.fromEntries(list.map((c) => [c.id, c])),
    loaded: !!r.data,
    error: r.error,
    reload: r.reload,
  };
}

/** This page's lists load the categories again; the stream tells the other pages. */
export function categoriesChanged() {
  changes.value = { ...changes.value, category: (changes.value.category || 0) + 1 };
}

/** A category (S7.2) as a draft saves it. */
export class CategoryRec extends Record {
  /** @override */
  static prefix = 'Cat';
  /** @override */
  static fields = FIELDS.CategoryRecord;
  /** @override */
  static defaults = { kind: 'expense', parentId: null, taxTag: null, keepReceiptsYears: null };
}

/**
 * Add a category in its own dialog, from a list outside a dialog (a transaction's row, bulk
 * categorise); resolves with the category made, or nothing.
 * @param {{ kind?: string }} [o]
 * @returns {Promise<any>}
 */
export function addCategory(o = {}) {
  return openDialog(CategoryDialog, { cat: null, kind: o.kind }).then((saved) => {
    const made = saved?.find?.((/** @type {any} */ x) => x.entity === 'Cat')?.record;
    if (made) categoriesChanged();
    return made || null;
  });
}

/** The top-level categories, for a parent. @param {any[]} list @param {string} [but] */
function parents(list, but) {
  return list.filter((c) => !c.parentId && c.id !== but);
}

/**
 * The fields of a new category made from a list inside a dialog (a transaction's, a rule's, a
 * plan line's, a loan's): in the same draft, saved with the dialog (S12.15.7).
 * @param {{ cat: CategoryRec, list: any[], idPrefix: string }} p
 */
function NewCategoryFields({ cat, list, idPrefix }) {
  return html`
    <div class="sub-form" role="group" aria-label="New category">
      <div class="row">
        <${RecField} rec=${cat} name="name" label="New category" id=${idPrefix + '-name'}
          help="new-category" />
        <${RecField} rec=${cat} name="parentId" label="Under" id=${idPrefix + '-parent'}
          help="new-category-under" options=${[
            ['', 'Nothing: a top-level category'],
            ...parents(
              list,
            ).map((c) => [c.id, c.path]),
          ]} />
      </div>
      <div class="row">
        <${RecField} rec=${cat} name="kind" label="Kind" id=${idPrefix + '-kind'}
          help="new-category-kind" options=${KINDS} />
        <${RecField} rec=${cat} name="taxTag" label="Tax tag" id=${idPrefix + '-tag'}
          help="new-category-tax-tag" options=${TAX_TAGS} />
      </div>
    </div>
  `;
}

/** The new category a record's field names, made in this draft, if any. */
export function addedFor(/** @type {any} */ draft, /** @type {any} */ value) {
  return /** @type {CategoryRec | undefined} */ (draft?.records.find((/** @type {any} */ r) =>
    r instanceof CategoryRec && r.state === 'new' && !r.removed && r.id === value
  ));
}

/**
 * A record's category, chosen from the list, or made there with New category… (S12.2.6): the
 * new one's fields open below, in the dialog's draft. Bare, inside a Field of a row (a split's
 * part), it draws the choice alone, and `NewCategoryFor` draws the fields after the row.
 * @param {{ rec: any, name: string, draft: import('../app/draft.js').Draft | null,
 *   label: string, first?: [string, string] | null, id?: string, help?: string,
 *   bare?: boolean, hint?: any, kind?: string, disabled?: boolean,
 *   only?: (c: any) => boolean }} p
 */
export function CategoryField(p) {
  const { rec, name, draft } = p;
  const cats = useCategories();
  const value = rec.get(name);
  const added = addedFor(draft, value);
  const pick = (/** @type {string} */ v) => {
    if (v === NEW) {
      if (added || !draft) return;
      const made = draft.add(CategoryRec, { name: '', kind: p.kind || 'expense' });
      rec.set(name, made.id);
      return;
    }
    if (added) draft?.remove(added);
    rec.input(name, v);
  };
  // Its Field's id, as the Field gives it: the label's slug unless one is given.
  const id = p.id || slug(p.label);
  // Bare, the Field around it names it: its id as that Field gives its control (fields.js).
  const own = p.bare
    ? { id: (p.help ? 'x-' : 'f-') + id, 'aria-label': p.label, 'data-help': p.help }
    : {};
  const select = html`
    <${Select} value=${added ? NEW : value ?? ''} onChange=${pick} disabled=${p.disabled}
      options=${categoryOptions(
        p.only ? cats.list.filter(p.only) : cats.list,
        p.first === undefined ? ['', 'Uncategorised'] : p.first,
      )}
      ...${own} />
  `;
  if (p.bare) return select;
  return html`
    <${Field} label=${p.label} id=${p.id} help=${p.help} hint=${p.hint}
      error=${rec.error(name)}>${select}</${Field}>
    ${added ? html`<${NewCategoryFields} cat=${added} list=${cats.list} idPrefix=${id} />` : null}
  `;
}

/**
 * The fields of the new category a bare `CategoryField` made, drawn where the row allows.
 * @param {{ rec: any, name: string, draft: import('../app/draft.js').Draft | null, id: string }} p
 */
export function NewCategoryFor({ rec, name, draft, id }) {
  const cats = useCategories();
  const added = addedFor(draft, rec.get(name));
  return added
    ? html`<${NewCategoryFields} cat=${added} list=${cats.list} idPrefix=${id} />`
    : null;
}

/** Why a field is locked for the reader (S7.2.3). @param {any} c */
function lockedWhy(c) {
  if (c.serverNamed) {
    return 'MoolaKata counts in this category by its own rules: only admins change its parent and tax tag, and its kind stays.';
  }
  if (c.shipped) return 'Only admins change a shipped category’s parent, kind and tax tag.';
  if (c.createdById !== session.value?.user?.id) {
    return 'Only admins change another user’s category’s parent, kind and tax tag.';
  }
  return 'It’s in use now: only admins change its parent, kind and tax tag.';
}

/**
 * Add or edit a category (S7.2.3). Resolves with what was saved.
 * @param {{ close: (v?: any) => void, cat: any | null, kind?: string, parentId?: string }} p
 */
export function CategoryDialog({ close, cat, kind, parentId }) {
  useDialogGuide('dialog-edit-category');
  const cats = useCategories();
  const f = useDraft((draft) => {
    if (cat) draft.load(CategoryRec, cat);
    else draft.add(CategoryRec, { name: '', kind: kind || 'expense', parentId: parentId || null });
  }, [cat?.id]);
  const rec = /** @type {CategoryRec | undefined} */ (f.draft?.records[0]);
  const locked = !!cat && !cat.allowed.change;
  const hasKids = !!cat && cats.list.some((c) => c.parentId === cat.id);
  return html`
    <${DraftDialog} f=${f} title=${cat ? `Edit ${cat.path}` : 'New category'} close=${close}
      what="This category" label=${cat ? 'Save' : 'Add the category'}
      done=${cat ? 'Category saved' : 'Category added'}
      saved=${(/** @type {any} */ o) => {
        toast(cat ? 'Category saved' : 'Category added');
        categoriesChanged();
        close(o.saved);
      }}
      extra=${({ save }) =>
        cat?.allowed.delete
          ? html`<button type="button" class="btn danger" onClick=${async () => {
            if (!f.draft || !rec) return;
            const sure = await confirmAction({
              title: `Delete ${cat.path}?`,
              detail: 'Nothing uses it, so nothing else changes.',
            });
            if (!sure) return;
            f.draft.remove(rec);
            const out = await save.run().catch(() => null);
            if (out?.status !== 'saved') f.draft.unremove(rec);
          }}>Delete</button>`
          : null}>
      ${rec
        ? html`
          <${RecField} rec=${rec} name="name" label="Name"
            hint="Up to 60 characters. Anyone may rename a category; everyone sees the new name." />
          <${RecField} rec=${rec} name="parentId" label="Under"
            disabled=${locked || hasKids} options=${[
              ['', 'Nothing: a top-level category'],
              ...parents(cats.list, cat?.id).map((c) => [c.id, c.path]),
            ]} hint=${hasKids
              ? 'It has categories of its own, so it stays at the top.'
              : locked
              ? lockedWhy(cat)
              : undefined} />
          <div class="row">
            <${RecField} rec=${rec} name="kind" label="Kind"
              disabled=${locked || cat?.serverNamed} options=${KINDS} />
            <${RecField} rec=${rec} name="taxTag" label="Tax tag"
              disabled=${locked} options=${TAX_TAGS}
              hint="Puts its transactions in Taxes › Deductions." />
          </div>
          ${cat && !cat.allowed.delete && !cat.serverNamed
            ? html`<p class="small dim">${
              cat.inUse
                ? (cat.allowed.merge
                  ? 'In use: merge it into another category rather than delete it.'
                  : 'In use: an admin can merge it into another category.')
                : 'Only admins delete a shipped category or another user’s.'
            }</p>`
            : null}
        `
        : null}
    </${DraftDialog}>
  `;
}

/**
 * An admin's merge of a category into another (S7.2.4): each of its own categories moves
 * across or merges into one of the other's; the budgets whose plans change are named first.
 * @param {{ close: (v?: any) => void, cat: any }} p
 */
export function MergeDialog({ close, cat }) {
  useDialogGuide('dialog-merge-category');
  const cats = useCategories();
  const targets = mergeTargets(cat, cats.list);
  const [into, setInto] = useState('');
  const [mapping, setMapping] = useState(/** @type {{ [id: string]: string }} */ ({}));
  const [budgets, setBudgets] = useState(/** @type {string[] | null} */ (null));
  const [problem, setProblem] = useState(/** @type {any} */ (null));
  const kids = cats.list.filter((c) => c.parentId === cat.id);
  const theirs = cats.list.filter((c) => into && c.parentId === into);
  const choose = (/** @type {string} */ v) => {
    setInto(v);
    setMapping(defaultMapping(kids, cats.list.filter((c) => v && c.parentId === v)));
  };
  useEffect(() => {
    setBudgets(null);
    setProblem(null);
    if (!into) return;
    let live = true;
    api.post(`/categories/${cat.id}/merge-preview`, { into, children: mapping }).then(
      (r) => live && setBudgets(r.budgets),
      (e) => live && setProblem(e),
    );
    return () => {
      live = false;
    };
  }, [into, JSON.stringify(mapping)]);
  const run = useSubmit(async () => {
    const target = cats.byId[into];
    const sure = await confirmAction({
      title: `Merge ${cat.path} into ${target?.path}?`,
      detail: 'Everything filed under it moves, for every user, and it is deleted.',
      yes: 'Merge',
    });
    if (!sure) return;
    const out = await api.post(`/categories/${cat.id}/merge`, { into, children: mapping }, {
      version: cat.version,
    });
    toast(`Merged into ${out.into.path}`);
    categoriesChanged();
    close(out);
  });
  const err = (/** @type {string} */ field) =>
    [run.error, problem].flatMap((e) => e?.errors || []).find((/** @type {any} */ x) =>
      x.field === field
    )?.message;
  return html`
    <${Dialog} title=${`Merge ${cat.path}`} close=${close} wide=${kids.length > 0}
      onSubmit=${() => run.run().catch(() => {})}
      footer=${html`<button class="btn danger" disabled=${
        run.busy || !into || !!problem
      }>Merge</button>`}>
      ${!cats.loaded ? html`<${Loading} lines=${3} />` : html`
        <p class="small dim" style=${{ marginTop: 0 }}>Everything filed under ${cat
          .path} (transactions,
          splits, rules, plan lines, moves, a loan's category) moves to the one
          you choose, for every user, and ${cat.path} is deleted.</p>
        <${Field} label="Into" id="merge-into" error=${err('into')}
          hint=${`Another ${KIND_NAMES[cat.kind].toLowerCase()} category${
            kids.length ? ' at the top level, since it has categories of its own' : ''
          }.`}>
          <${Select} value=${into} onChange=${choose} options=${[
            ['', 'Choose…'],
            ...targets.map((c) => [c.id, c.path]),
          ]} />
        </${Field}>
        ${into && kids.length
          ? html`
            <h4 data-help="merge-children">Its categories</h4>
            ${kids.map((k) =>
              html`
                <${Field} label=${k.name} id=${'merge-child-' + k.id} help="merge-children"
                  error=${err('children.' + k.id)}>
                  <${Select} value=${mapping[k.id] ?? k.id} onChange=${(/** @type {string} */ v) =>
                    setMapping({ ...mapping, [k.id]: v })} options=${[
                    [k.id, `${k.name} (moves across)`],
                    ...theirs.map((t) => [t.id, t.name]),
                  ]} />
                  </${Field}>
              `
            )}
          `
          : null}
        ${into && budgets
          ? html`<p class="small" data-help="merge-budgets">${
            budgets.length
              ? html`The plans of ${budgets.join(', ')} change: where a budget plans both, it plans
                  both amounts in one line.`
              : 'No budget you can see plans it.'
          }</p>`
          : null}
        ${problem && !problem.errors?.some((/** @type {any} */ x) => x.field)
          ? html`<${FormError} error=${problem} />`
          : null}
        <${FormError} error=${run.error?.errors?.some((/** @type {any} */ x) => x.field)
          ? null
          : run.error} />
      `}
    </${Dialog}>
  `;
}

/** A category's row in the tree. @param {{ c: any, child?: boolean }} p */
function CategoryRow({ c, child }) {
  const me = session.value?.user?.id;
  const by = c.shipped
    ? 'shipped'
    : c.createdById === me
    ? 'you'
    : c.createdByName || 'a former user';
  return html`
    <tr>
      <td class=${child ? 'child' : ''}>${child
        ? html`<span class="dim" aria-hidden="true">└ </span>${c.name}`
        : html`<b>${c.name}</b>`}</td>
      <td>${KIND_NAMES[c.kind]}</td>
      <td>${c.taxTag ? html`<span class="pill">${TAG_NAMES[c.taxTag]}</span>` : null}</td>
      <td class="small dim">${by}</td>
      <td class="num" style=${{ whiteSpace: 'nowrap' }}>
        <button type="button" class="btn sm" aria-label=${`Edit ${c.path}`}
          onClick=${() => openDialog(CategoryDialog, { cat: c })}>Edit</button>
        ${c.allowed.merge
          ? html`
            <button type="button" class="btn sm" aria-label=${`Merge ${c.path}`}
              onClick=${() => openDialog(MergeDialog, { cat: c })}>Merge…</button>
          `
          : null}
      </td>
    </tr>
  `;
}

/** Budgets › Categories (S12.2.6): the household's tree, every user's. */
export function CategoriesTab() {
  const cats = useCategories();
  if (cats.error) return html`<${Failed} error=${cats.error} />`;
  if (!cats.loaded) return html`<${Loading} lines=${8} />`;
  const tops = cats.list.filter((c) => !c.parentId);
  return html`
    <div class="toolbar">
      <span class="small dim">One tree for the household: everyone files under the same
        categories, in every budget.</span><span class="spacer"></span>
      <button type="button" class="btn" onClick=${() => addCategory()}><${Icon}
        name="plus" /> Add a category</button>
    </div>
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table class="t categories">
          <caption class="sr-only">Categories</caption>
          <thead>
            <tr>
              <th>Category</th>
              <th>Kind</th>
              <th>Tax tag</th>
              <th>Added by</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${tops.map((t) =>
            html`
              <${CategoryRow} c=${t} />
              ${cats.list.filter((c) => c.parentId === t.id).map((c) =>
                html`<${CategoryRow} c=${c} child />`
              )}
            `
          )}</tbody>
        </table>
      </div>
    </div>
  `;
}
