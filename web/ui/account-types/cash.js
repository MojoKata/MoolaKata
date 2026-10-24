// The Cash account type (requirements S1.1): cash on hand, kept by hand; its fields, icon and
// help part.
/** @type {import('./index.js').AccountType} */
export default {
  type: 'cash',
  label: 'Cash',
  group: 'banking',
  icon: 'wallet',
  hint: 'Cash on hand, kept by hand',
  investing: false,
  reconcilable: false,
  contributions: false,
};
