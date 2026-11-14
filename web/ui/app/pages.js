// The page of the record an id names (S12.18.6.2): an account, a budget, a portfolio or a
// projection has one; the kit's lists link to it (`linkRecords`).
const PAGES = /** @type {{ [prefix: string]: (id: string) => string }} */ ({
  Acct: (id) => `/ui/accounts/${id}`,
  Bdgt: (id) => `/ui/budgets/${id}/month`,
  Portf: (id) => `/ui/portfolios/${id}`,
  Prjct: (id) => `/ui/projections/${id}`,
});

/** The page of the record an id names, or null where its kind has none. @param {any} id */
export function pageOf(id) {
  const prefix = /^([A-Za-z]+)_/.exec(String(id ?? ''))?.[1];
  return prefix && PAGES[prefix] ? PAGES[prefix](String(id)) : null;
}
