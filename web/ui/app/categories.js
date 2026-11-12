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
