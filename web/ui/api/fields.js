// Generated from the API's OpenAPI document by `web/dev.sh codegen`.
// Do not edit: web/check fails when this file differs from what the routes give.

/** @type {Record<string, Record<string, import('../app/draft.js').FieldSpec>>} */
export const FIELDS = {
  LineIn: {
    budgetId: {"type": "ref", "prefix": "Bdgt"},
    categoryId: {"type": "ref", "prefix": "Cat"},
    fromMonth: {"type": "date"},
    amount: {"type": "money"},
    cadence: {"type": "choice", "choices": ["month", "year"]},
    rollover: {"type": "bool"},
    overspend: {"type": "choice", "choices": ["carry", "next"]},
    projectionId: {"type": "ref", "prefix": "Prjct", "nullable": true},
    target: {"type": "money", "nullable": true},
    heldInId: {"type": "ref", "prefix": "Acct", "nullable": true},
  },
};
