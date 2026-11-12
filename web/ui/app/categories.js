// What the category screens work out from the list alone (requirements S7.2.3, S7.2.4,
// S12.2.6): the lists to choose from and what a merge may take. No imports, so the unit tests
// read it alone.

/** The choice that adds a category, at the end of a list of them. */
export const NEW = 'new-category';

/**
 * A list of categories to choose from: `first` (none, or leave as it is), each by its path,
 * and New category… at the end.
 * @param {any[]} list @param {[string, string] | null} [first]
 * @returns {[string, string][]}
 */
export function categoryOptions(list, first = ['', 'Uncategorised']) {
  /** @type {[string, string][]} */
  const out = first ? [first] : [];
  for (const c of list) out.push([c.id, c.path]);
  out.push([NEW, 'New category…']);
  return out;
}

/** The categories a source may merge into (S7.2.4). @param {any} source @param {any[]} list */
export function mergeTargets(source, list) {
  const kids = list.some((c) => c.parentId === source.id);
  return list.filter((c) =>
    c.id !== source.id && c.parentId !== source.id && c.kind === source.kind &&
    (!kids || !c.parentId)
  );
}

/**
 * Where each of the source's own categories goes when it merges into `into`: one of the
 * target's with the same name, in any case, else itself (S7.2.4).
 * @param {any[]} kids @param {any[]} theirs @returns {{ [id: string]: string }}
 */
export function defaultMapping(kids, theirs) {
  return Object.fromEntries(kids.map((k) => {
    const same = theirs.find((t) => t.name.toLowerCase() === k.name.toLowerCase());
    return [k.id, same ? same.id : k.id];
  }));
}

/**
 * How many uses the reader can see and how many they can't, as a category's dialog and a
 * refused delete say it (S12.2.6).
 * @param {number} seen @param {number} unseen
 */
export function usesWords(seen, unseen) {
  const s = seen === 1 ? '' : 's';
  if (!unseen) return `${seen} use${s} you can see`;
  if (!seen) return `${unseen} use${unseen === 1 ? '' : 's'} you can't see`;
  return `${seen} use${s} you can see, and ${unseen} you can't`;
}

/** The kinds of use, in the tour's order, with each step's title (S12.17.6). */
export const USE_KINDS = /** @type {const} */ ([
  ['transactions', 'Transactions and their parts'],
  ['rules', 'Rules'],
  ['planLines', 'Plan lines'],
  ['moves', 'Moves'],
  ['loans', 'Loans'],
  ['categories', 'Categories under it'],
]);

/** How many of each kind of use, and in all. @param {any} u @returns {Record<string, number>} */
export function useCounts(u) {
  return Object.fromEntries([
    ...USE_KINDS.map(([k]) => [k, k === 'transactions' ? u.transactions : u[k].length]),
    ['seen', u.seen],
  ]);
}

/** "2026-03-01" as "Mar 2026". @param {string} day */
export function monthName(day) {
  const [y, m] = day.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
}

/**
 * @typedef {{ label: string, href: string }} UseLink
 * @typedef {{ label: string, href?: string, links?: UseLink[] }} UseItem
 * @typedef {{ kind: string, title: string, count: number, done: boolean, items: UseItem[] }} UseStep
 */

/**
 * The Find uses tour's steps (S12.17.6): one for each kind of use the reader could see when it
 * started or can see now, with its count and links; a kind cleared since stays, done.
 * @param {any} u  the category's uses now (GET /categories/{id}/uses)
 * @param {Record<string, number>} start  the counts when the tour started
 * @param {string} catId
 * @returns {UseStep[]}
 */
export function useSteps(u, start, catId) {
  const now = useCounts(u);
  /** @type {Record<string, UseItem[]>} */
  const items = {
    transactions: now.transactions
      ? [{
        label: `${now.transactions} transaction${now.transactions === 1 ? '' : 's'} filed under it`,
        href: `/ui/transactions?category=${catId}`,
      }]
      : [],
    rules: u.rules.map((/** @type {any} */ r) => ({
      label: r.payeeMatch.toLowerCase().startsWith('re:') ? r.payeeMatch : `“${r.payeeMatch}”`,
      href: `/ui/transactions/rules/${r.id}`,
    })),
    planLines: u.planLines.map((/** @type {any} */ x) => ({
      label: `${x.budgetName}, from ${monthName(x.month)}`,
      href: `/ui/budgets/${x.budgetId}/month?month=${x.month.slice(0, 7)}`,
    })),
    moves: byBudget(u.moves),
    loans: u.loans.map((/** @type {any} */ x) => ({
      label: x.name,
      href: `/ui/accounts/${x.accountId}/settings`,
    })),
    categories: u.categories.map((/** @type {any} */ x) => ({
      label: x.name,
      href: '/ui/budgets/none/categories',
    })),
  };
  return USE_KINDS.filter(([k]) => (start[k] || 0) > 0 || now[k] > 0).map(([k, title]) => ({
    kind: k,
    title,
    count: now[k],
    done: now[k] === 0,
    items: items[k],
  }));
}

/** A budget's moves, one line for each budget with a link to each month. @param {any[]} moves */
function byBudget(moves) {
  /** @type {Map<string, UseItem & { links: UseLink[] }>} */
  const out = new Map();
  for (const x of moves) {
    const line = out.get(x.budgetId) || { label: `${x.budgetName}: `, links: [] };
    const href = `/ui/budgets/${x.budgetId}/month?month=${x.month.slice(0, 7)}`;
    if (!line.links.some((l) => l.href === href)) {
      line.links.push({ label: monthName(x.month), href });
    }
    out.set(x.budgetId, line);
  }
  return [...out.values()];
}
